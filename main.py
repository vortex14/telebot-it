from aiogram.utils.exceptions import MessageNotModified, Throttled
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram import Bot, Dispatcher, executor, md, types
from aiogram.utils.callback_data import CallbackData
from aiogram.dispatcher import FSMContext
from aiogram.types import ChatType, ParseMode, ContentTypes
from markupsafe import Markup
from notion_client import AsyncClient, Client
import asyncio
import logging
import random
import uuid
import typing
import os
import aiohttp, json

logging.basicConfig(level=logging.INFO)

notion = Client(auth=os.environ["NOTION_TOKEN"])
bot = Bot(token=os.environ["BOT_TOKEN"], parse_mode=types.ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

FINAL_MESSAGE = "Спасибо, за обращение. После изучения вашей ситуации свяжемся по телеграмму или перезвоним вам."
headers = {
    "Notion-Version": "2021-08-16",
    "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}"
}

class Form(StatesGroup):
    name = State()
    photo = State()
    problem = State()
    image_done = State()
    phone = State()
    company_name = State()
    type_request = State()



def get_notion_body(company: str = "", name: str = "", q: str = "", phone: str = "", photos: list = []):

    _photos = [{

            "name": str(i),
            "type": "external",
            "external": {
                "url": photos[i]
            }

    } for i in range(0, len(photos))]
    return {
        "parent": {
            "type": "database_id",
            "database_id": os.environ["NOTION_DB"]
        },
        "properties": {
            "Название организации (или ФИО физ. лица)": {
                "type": "title",
                "title": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"{name} | {company}"
                        }
                    }
                ]
            },
            "Вопрос": {
                "type": "rich_text",
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": q
                        }
                    }
                ]
            },
            "Номер телефона": {
                "type": "rich_text",
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": phone
                        }
                    }
                ]
            },
            "Скриншот проблемы": {
                "type": "files",
                "files": _photos
            }
            
        }
}


async def save_to_notion(company: str = "", name: str = "", q: str = "", phone: str = "", photos: list = []):
    body = get_notion_body(company, name, q, phone, photos)
    async with aiohttp.ClientSession() as session:       
        async with session.post("https://api.notion.com/v1/pages", json=body, headers={
            "Notion-Version": "2021-08-16",
            "Authorization": f"Bearer {os.environ['NOTION_TOKEN']}"
        }) as response:
            c = await response.text()
            print("Отправлено в ноушен. Статус код: ",response.status)
            if response.status != 200:
                print(c)

@dp.message_handler(commands='menu')
async def remove_all(message: types.Message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add("/start")
    # markup.add("/remove_all")

    await message.answer("Доступные команды", reply_markup=markup)

@dp.message_handler(commands='start')
async def cmd_start(message: types.Message):
    await Form.name.set()
    await message.answer('Здравствуйте, как к вам обращаться?', reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=None)
async def invalid(message: types.Message, state: FSMContext):
    await message.answer("Для общения с ботом перейдите по /start")

@dp.message_handler(state=Form.name)
async def on_new_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await Form.problem.set()
    await message.answer(f'{message.text}, опишите вашу проблему', reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(lambda message: message.text not in ("да", "нет", "Отправить и сохранить"), state=Form.problem)
async def on_new_name(message: types.Message, state: FSMContext):
    await state.update_data(problem=message.text)
    st = await state.get_data()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add("да")
    markup.add("нет") 
    await message.answer("есть ли скриншоты", reply_markup=markup)


async def append_photo(url:str, state: FSMContext):
    cs = await state.get_data()
    if cs.get("photos"):
        photos = cs["photos"] + [url]
    else:
        photos = [url]    
    await state.update_data(photos=photos)

@dp.message_handler(content_types=ContentTypes.PHOTO, state=Form.problem)
async def on_image(message: types.Message, state: FSMContext):
    print("recivied photo !")
    ph = message.photo.pop()
    phd = await ph.get_file()
    url = f"https://api.telegram.org/file/bot{os.environ['BOT_TOKEN']}/{phd['file_path']}"
    await append_photo(url, state)

    cs = await state.get_data()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add("Отправить и сохранить")
    await message.reply(f"Загружено: {len(cs['photos'])}", reply_markup=markup)

@dp.message_handler(lambda message: "да" in message.text, state=Form.problem)
async def on_screenshot(message: types.Message, state: FSMContext):
    await message.answer("присылайте в чат скришоты", reply_markup=types.ReplyKeyboardRemove())




@dp.message_handler(lambda message:  message.text in ("Отправить и сохранить", "нет"), state=Form.problem)
async def on_image_done(message: types.Message, state: FSMContext):
    await Form.phone.set()
    await message.reply(f"Напишите номер телефона для связи", reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(state=Form.phone)
async def on_phone(message: types.Message, state: FSMContext):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, selective=True)
    markup.add("физ. лицо")
    markup.add("компания")
    await Form.type_request.set()
    await state.update_data(phone=message.text)
    await message.reply("Вы как?", reply_markup=markup)

@dp.message_handler(lambda message: "компания" in message.text, state=Form.type_request)
async def on_company_request(message: types.Message, state: FSMContext):
    await Form.company_name.set()
    await message.answer('Как называется ваша компания?', reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(lambda message: "физ. лицо" in message.text, state=Form.type_request)
async def on_personal_request(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await save_to_notion("", data["name"], data["problem"], data["phone"], data.get("photos") or [])


    await state.finish()

    await message.answer(FINAL_MESSAGE, reply_markup=types.ReplyKeyboardRemove())


@dp.message_handler(state=Form.company_name)
async def on_company_name(message: types.Message, state: FSMContext):
    await state.update_data(company=message.text)
    data = await state.get_data()

    await save_to_notion(data["company"], data["name"], data["problem"], data["phone"], data["photos"])

    await state.finish()
    await message.answer(FINAL_MESSAGE, reply_markup=types.ReplyKeyboardRemove())


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
