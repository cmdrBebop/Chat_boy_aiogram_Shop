import logging

from aiocryptopay import AioCryptoPay
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.types.chat import ChatActions
from aiogram.utils.markdown import hlink

from data.config import CRYPTO_PAY_TOKEN, ADMINS
from filters import IsUser
from keyboards.default.markups import *
from keyboards.inline.payment import *
from keyboards.inline.products_from_cart import product_markup
from keyboards.inline.products_from_catalog import product_cb
from loader import bot, db, dp
from states import CheckoutState
from states.cryptobot import CryproBot
from utils.cryptobot_pay import get_crypto_bot_sum, check_crypto_bot_invoice
from .menu import cart


@dp.message_handler(IsUser(), text=cart)
async def process_cart(message: Message, state: FSMContext):
    cart_data = db.fetchall(
        'SELECT * FROM cart WHERE cid=?', (message.chat.id,))

    if len(cart_data) == 0:
        await message.answer('Ваша корзина пуста.')
    else:
        await bot.send_chat_action(message.chat.id, ChatActions.TYPING)
        async with state.proxy() as data:
            data['products'] = {}
        order_cost = 0

        for _, idx, count_in_cart in cart_data:
            product = db.fetchone('SELECT * FROM products WHERE idx=?', (idx,))
            if product == None:
                db.query('DELETE FROM cart WHERE idx=?', (idx,))
            else:
                _, title, body, image, price, _ = product
                order_cost += price

                async with state.proxy() as data:
                    data['products'][idx] = [title, price, count_in_cart]

                markup = product_markup(idx, count_in_cart)
                text = f'<b>{title}</b>\n\n{body}\n\nЦена: {price}₽.'
                await message.answer_photo(photo=image,
                                           caption=text,
                                           reply_markup=markup)

        if order_cost != 0:
            markup = ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
            markup.add('📦 Оформить заказ')
            await message.answer('Перейти к оформлению?',
                                 reply_markup=markup)


@dp.callback_query_handler(IsUser(), product_cb.filter(action='count'))
@dp.callback_query_handler(IsUser(), product_cb.filter(action='increase'))
@dp.callback_query_handler(IsUser(), product_cb.filter(action='decrease'))
async def product_callback_handler(query: CallbackQuery, callback_data: dict,
                                   state: FSMContext):
    idx = callback_data['id']
    action = callback_data['action']

    if 'count' == action:
        async with state.proxy() as data:
            if 'products' not in data.keys():
                await process_cart(query.message, state)
            else:
                await query.answer('Количество - ' + data['products'][idx][2])
    else:
        async with state.proxy() as data:
            if 'products' not in data.keys():
                await process_cart(query.message, state)
            else:
                data['products'][idx][2] += 1 if 'increase' == action else -1
                count_in_cart = data['products'][idx][2]

                if count_in_cart == 0:
                    db.query('''DELETE FROM cart
                    WHERE cid = ? AND idx = ?''', (query.message.chat.id, idx))
                    await query.message.delete()
                else:
                    db.query('''UPDATE cart 
                    SET quantity = ? 
                    WHERE cid = ? AND idx = ?''',
                             (count_in_cart, query.message.chat.id, idx))
                    await query.message.edit_reply_markup(
                        product_markup(idx, count_in_cart))


@dp.message_handler(IsUser(), text='📦 Оформить заказ')
async def process_checkout(message: Message, state: FSMContext):
    await CheckoutState.check_cart.set()
    await checkout(message, state)


async def checkout(message, state):
    answer = ''
    total_price = 0

    async with state.proxy() as data:
        for title, price, count_in_cart in data['products'].values():
            tp = count_in_cart * price
            answer += f'<b>{title}</b> * {count_in_cart}шт. = {tp}₽\n'
            total_price += tp

    await message.answer(f'{answer}\nОбщая сумма заказа: {total_price}₽.',
                         reply_markup=check_markup())


@dp.message_handler(IsUser(),
                    lambda message: message.text not in [all_right_message,
                                                         back_message],
                    state=CheckoutState.check_cart)
async def process_check_cart_invalid(message: Message):
    await message.reply('Такого варианта не было.')


@dp.message_handler(IsUser(), text=back_message,
                    state=CheckoutState.check_cart)
async def process_check_cart_back(message: Message, state: FSMContext):
    await state.finish()
    await process_cart(message, state)


@dp.message_handler(IsUser(), text=all_right_message,
                    state=CheckoutState.check_cart)
async def process_check_cart_all_right(message: Message, state: FSMContext):
    await CheckoutState.next()
    await message.answer('Укажите свое имя.',
                         reply_markup=back_markup())


@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.name)
async def process_name_back(message: Message, state: FSMContext):
    await CheckoutState.check_cart.set()
    await checkout(message, state)


@dp.message_handler(IsUser(), state=CheckoutState.name)
async def process_name(message: Message, state: FSMContext):
    async with state.proxy() as data:

        data['name'] = message.text

        if 'address' in data.keys():

            await confirm(message)
            await CheckoutState.confirm.set()

        else:

            await CheckoutState.next()
            await message.answer('Укажите адрес доставки заказа.',
                                 reply_markup=back_markup())


@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.address)
async def process_address_back(message: Message, state: FSMContext):
    async with state.proxy() as data:
        await message.answer('Изменить имя с <b>' + data['name'] + '</b>?',
                             reply_markup=back_markup())

    await CheckoutState.name.set()


@dp.message_handler(IsUser(), state=CheckoutState.address)
async def process_address(message: Message, state: FSMContext):
    async with state.proxy() as data:
        data['address'] = message.text

    await confirm(message)
    await CheckoutState.next()


async def confirm(message):
    await message.answer('Убедитесь, что все правильно оформлено и подтвердите заказ.', reply_markup=confirm_markup())


@dp.message_handler(IsUser(), lambda message: message.text not in [confirm_message, back_message],
                    state=CheckoutState.confirm)
async def process_confirm_invalid(message: Message):
    await message.reply('Такого варианта не было.')


@dp.message_handler(IsUser(), text=back_message, state=CheckoutState.confirm)
async def process_confirm(message: Message, state: FSMContext):
    await CheckoutState.address.set()

    async with state.proxy() as data:
        await message.answer('Изменить адрес с <b>' + data['address'] + '</b>?',
                             reply_markup=back_markup())


@dp.message_handler(IsUser(), text=confirm_message, state=CheckoutState.confirm)
async def process_confirm(message: Message, state: FSMContext):
    markup = ReplyKeyboardRemove()

    logging.info('Deal was made.')

    async with state.proxy() as data:
        cid = message.chat.id
        products = [idx + '=' + str(quantity)
                    for idx, quantity in db.fetchall('''SELECT idx, quantity FROM cart
        WHERE cid=?''', (cid,))]

        total_amount = 0

        # db.query('INSERT INTO orders VALUES (?, ?, ?, ?)',
        #          (cid, data['name'], data['address'], ' '.join(products)))
        # db.query('DELETE FROM cart WHERE cid=?', (cid,))

        await message.answer(
            'Ваш заказ сформирован 🚀\nИмя: <b>' + data[
                'name'] + '</b>\nАдрес: <b>' + data['address'] + '</b>',
            reply_markup=markup)
        await message.answer(
            '<b>💳 Выберите способ пополнения:</b>',
            reply_markup=payment_methods_kb
        )

    await state.finish()
    # await CryproBot.sum.set()
    # await state.update_data(crypto_bot_sum=float(message.text))


# @dp.callback_query_handler(IsUser(), Text('crypto_bot'), state='*')
# async def crypto_bot_pay(call: types.CallbackQuery):
#     await call.message.edit_text(
#         f'<b>{hlink("⚜️ CryptoBot", "https://t.me/CryptoBot")}</b>\n\n'
#         '— Минимум: <b>0.1 $</b>\n\n'
#         f'<b>💸 Введите сумму пополнения в долларах</b>',
#         disable_web_page_preview=True,
#         reply_markup=back_to_add_balance_kb
#     )
#     await CryproBot.sum.set()


# @dp.message_handler(IsUser(), state=CryproBot.sum)
# async def crypto_bot_sum(message: types.Message, state: FSMContext):
@dp.callback_query_handler(IsUser(), Text('crypto_bot'), state=CryproBot.sum)
async def crypto_bot_sum(call: types.CallbackQuery, state: FSMContext):
    total_amount = 1000
    await call.message.answer(
        f'<b>{hlink("⚜️ CryptoBot", "https://t.me/CryptoBot")}</b>\n\n'
        f'— Сумма: <b>{total_amount} $</b>\n\n'
        '<b>💸 Выберите валюту, которой хотите оплатить счёт</b>',
        disable_web_page_preview=True,
        reply_markup=crypto_bot_currencies_kb()
    )
    await state.update_data(crypto_bot_sum=float(total_amount))
    await CryproBot.currency.set()


@dp.callback_query_handler(IsUser(), Text(startswith='crypto_bot_currency'), state=CryproBot.currency)
async def crypto_bot_currency(call: types.CallbackQuery, state: FSMContext):
    # try:
    await call.message.delete()
    data = await state.get_data()
    cryptopay = AioCryptoPay(CRYPTO_PAY_TOKEN, network='https://testnet-pay.crypt.bot')
    invoice = await cryptopay.create_invoice(
        asset=call.data.split('|')[1],
        amount=await get_crypto_bot_sum(
            data['crypto_bot_sum'],
            call.data.split('|')[1]
        )
    )
    await cryptopay.close()
    await state.update_data(crypto_bot_currency=call.data.split('|')[1])
    # await db.payments.add_new_payment(invoice.invoice_id, data['crypto_bot_sum'])
    db.query(f'INSERT INTO payments VALUES ({invoice.invoice_id}, {data["crypto_bot_sum"]})')
    await call.message.answer(
        f'<b>💸 Отправьте {data["crypto_bot_sum"]} $ {hlink("по ссылке", invoice.pay_url)}</b>',
        reply_markup=check_crypto_bot_kb(invoice.pay_url, invoice.invoice_id)
    )
    await state.reset_state(with_data=False)


@dp.callback_query_handler(IsUser(), Text(startswith='check_crypto_bot'), state='*')
async def check_crypto_bot(call: types.CallbackQuery):
    # payment = await db.payments.select_payment(int(call.data.split('|')[1]))
    payment = db.fetchone(f'SELECT * FROM payments WHERE invoice_id={call.data.split("|")[1]}')
    if payment:
        if await check_crypto_bot_invoice(int(call.data.split('|')[1])):
            # await db.payments.delete_payment(int(call.data.split('|')[1]))
            db.query(f'DELETE FROM payments WHERE invoice_id={call.data.split("|")[1]}')
            await call.answer(
                '✅ Оплата прошла успешно!',
                show_alert=True
            )
            await call.message.delete()
            await call.message.answer(
                f'<b>💸 Ваш баланс пополнен на сумму {payment[1]} $!</b>'
            )

            for admin in ADMINS:
                await call.bot.send_message(
                    admin,
                    f'<b>{hlink("⚜️ CryptoBot", "https://t.me/CryptoBot")}</b>\n'
                    f'<b>💸 Обнаружено пополнение от @{call.from_user.username} [<code>{call.from_user.id}</code>] '
                    f'на сумму {payment[1]} $!</b>'
                )
        else:
            await call.answer(
                '❗️ Вы не оплатили счёт!',
                show_alert=True
            )


@dp.callback_query_handler(IsUser(), Text('cancel'), state='*')
async def cancel_handler(call: types.CallbackQuery, state: FSMContext):
    await call.message.delete()
    await call.message.answer('❌')
    await state.reset_state(with_data=False)
