"""Generate a deterministic, fictional mixed-subject group chat.

Outputs are under data/ (gitignored). No real messages or personal data are used.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.schemas import AttachedFile, Message

ROOT = Path(__file__).resolve().parents[1]
MSK = timezone(timedelta(hours=3))
START = datetime(2026, 9, 7, 9, 0, tzinfo=MSK)
RNG = random.Random(20261111)

CHAT_DATA = {
    "synthetic_elektro": {
        "topics": ["цепь с двумя источниками", "осциллограмма", "закон Кирхгофа", "макет", "датчик тока"],
        "events": [
            (7, "STAROSTA", "starosta", "По электротехнике ЛР2: отчёт загружаем до 18 сентября, 23:59. Условие сейчас пришлю.", None, "lab2_condition.txt"),
            (8, "STUDENT_1", "student", "Это та, где два источника и таблица измерений?", 7, None),
            (9, "STAROSTA", "starosta", "Да. Схему тоже приложите, фото макета не заменяет расчёт.", 8, None),
            (25, "STUDENT_3", "student", "Кто-нибудь помнит, ЛР2 уже надо было сдавать?", None, None),
            (26, "STUDENT_4", "student", "В старом сообщении 18-е, я так и записал.", 25, None),
            (27, "TEACHER_1", "teacher", "Поправка по ЛР2: срок перенесли на 21 сентября до 18:00. Остальные лабораторные без изменений.", 7, None),
            (28, "STUDENT_3", "student", "О, спасибо. А то я уже хотела ночью отправлять.", 27, None),
            (41, "STAROSTA", "starosta", "ЛР3 по электротехнике сдаём до 2 октября. Не путайте с ЛР2: у третьей работы другая схема.", None, "lab3_template.txt"),
            (42, "STUDENT_2", "student", "Шаблон из прошлого семестра подойдёт?", 41, None),
            (43, "TEACHER_1", "teacher", "Нет, используйте файл из сообщения выше. Там добавлен раздел про погрешность.", 42, None),
            (56, "TEACHER_1", "teacher", "Консультация перед РК по электротехнике будет 8 октября в 16:20, аудитория 412.", None, None),
            (57, "STUDENT_5", "student", "А сама рубежка тоже восьмого?", 56, None),
            (58, "TEACHER_1", "teacher", "Нет, РК 12 октября в 10:15. Восьмого только консультация.", 57, None),
            (70, "STAROSTA", "starosta", "ЛР4 отменили на эту неделю. Не загружайте пустые отчёты в систему.", None, None),
            (71, "STUDENT_1", "student", "То есть ЛР3 остаётся, а четвёртую пока не делаем?", 70, None),
            (72, "STAROSTA", "starosta", "Именно. По третьей дедлайн не меняли.", 71, None),
        ],
        "questions": [
            ("Какой актуальный срок сдачи ЛР2 по электротехнике?", [27]),
            ("Какой срок ЛР2 называли сначала?", [7]),
            ("Нужно ли прикладывать схему к ЛР2?", [9]),
            ("Какую лабораторную по электротехнике сдавать до 2 октября?", [41]),
            ("Подойдёт ли старый шаблон для ЛР3?", [43]),
            ("Когда консультация перед РК по электротехнике?", [56]),
            ("Когда сама рубежка по электротехнике?", [58]),
            ("Какую лабораторную отменили на эту неделю?", [70]),
            ("Изменили ли дедлайн ЛР3 после отмены ЛР4?", [72]),
            ("Сколько баллов даёт ЛР2 по электротехнике?", []),
            ("В какой аудитории будет экзамен по электротехнике?", []),
        ],
    },
    "synthetic_algo": {
        "topics": ["дерево поиска", "повороты в AVL", "хеш-таблица", "сложность обхода", "очередь с приоритетом"],
        "events": [
            (6, "TEACHER_2", "teacher", "По алгоритмам ДЗ1: реализовать AVL-дерево, тесты и короткое описание. Срок 17 сентября до 20:00.", None, "avl_requirements.txt"),
            (7, "STUDENT_6", "student", "Встроенные контейнеры можно для хранения узлов?", 6, None),
            (8, "TEACHER_2", "teacher", "Список для служебных целей можно. Само дерево должно быть вашей реализацией.", 7, None),
            (22, "STAROSTA", "starosta", "Кажется, ДЗ1 передвинули на пятницу, но я ещё уточняю. Пока не считайте это официальным переносом.", None, None),
            (23, "STUDENT_7", "student", "Я уже всем написала про пятницу 😬", 22, None),
            (24, "TEACHER_2", "teacher", "Нет, по ДЗ1 срок прежний: 17 сентября, 20:00. Сообщение о переносе было ошибкой.", 22, None),
            (38, "TEACHER_2", "teacher", "ЛР2 по алгоритмам: сравните хеш-таблицу с деревом на трёх наборах данных. Сдача до 6 октября.", None, "hash_lab2.txt"),
            (39, "STUDENT_8", "student", "Три набора — это разные размеры или разные распределения ключей?", 38, None),
            (40, "TEACHER_2", "teacher", "Разные распределения. Размеры тоже укажите в отчёте, но это не три отдельных задания.", 39, None),
            (53, "STAROSTA", "starosta", "Напоминаю: контрольная по алгоритмам 15 октября в 13:00. Темы: деревья, хеширование, графы.", None, None),
            (54, "STUDENT_9", "student", "А графы будут с кодом или только задачи на бумаге?", 53, None),
            (55, "TEACHER_2", "teacher", "Только задачи на бумаге. Но оценку сложности надо объяснить словами.", 54, None),
            (68, "STUDENT_6", "student", "Мне бот пишет, что ЛР2 по алгоритмам до второго октября. Это же срок по электротехнике?", None, None),
            (69, "STAROSTA", "starosta", "Да, это разные предметы. По алгоритмам ЛР2 до 6 октября, смотри сообщение преподавателя.", 68, None),
        ],
        "questions": [
            ("Когда сдавать ДЗ1 по алгоритмам?", [24]),
            ("Правда ли ДЗ1 перенесли на пятницу?", [24]),
            ("Что требуется сделать в ДЗ1 по алгоритмам?", [6]),
            ("Можно ли использовать встроенный список в ДЗ1?", [8]),
            ("Когда сдавать ЛР2 по алгоритмам?", [38]),
            ("Что означают три набора данных в ЛР2?", [40]),
            ("Когда контрольная по алгоритмам?", [53]),
            ("Контрольная по графам будет с кодом?", [55]),
            ("Почему второе октября не срок ЛР2 по алгоритмам?", [68, 69]),
            ("Будет ли пересдача контрольной по алгоритмам?", []),
            ("Сколько задач будет на контрольной по алгоритмам?", []),
        ],
    },
    "synthetic_models": {
        "topics": ["нормализация", "ER-диаграмма", "связи многие-ко-многим", "запрос с JOIN", "транзакции"],
        "events": [
            (5, "TEACHER_3", "teacher", "По моделям данных курсовая: первый этап — ER-диаграмма и список сущностей. Дедлайн 25 сентября.", None, "course_stage1.txt"),
            (6, "STUDENT_10", "student", "Сущности можно пока без атрибутов?", 5, None),
            (7, "TEACHER_3", "teacher", "Нет, ключевые атрибуты укажите сразу. Полную схему таблиц позже.", 6, None),
            (20, "TEACHER_3", "teacher", "Второй этап курсовой по моделям данных — схема таблиц и ограничения. Срок 16 октября.", None, "course_stage2.txt"),
            (21, "STUDENT_11", "student", "Первый этап тоже до 16-го?", 20, None),
            (22, "TEACHER_3", "teacher", "Нет, 16 октября только второй этап. Первый остаётся до 25 сентября.", 21, None),
            (35, "STAROSTA", "starosta", "На лекции сказали, что ЛР2 по моделям до 7 октября. Я позже проверю в чате преподавателя.", None, None),
            (36, "TEACHER_3", "teacher", "Уточняю по ЛР2: окончательный срок 9 октября до 23:59. Седьмое было в черновике расписания.", 35, "lab2_models.txt"),
            (49, "STUDENT_12", "student", "Можно для ЛР2 взять тему интернет-магазина?", 36, None),
            (50, "TEACHER_3", "teacher", "Можно, если покажете связь заказа с позициями и объясните ограничения целостности.", 49, None),
            (63, "TEACHER_3", "teacher", "РК по моделям данных — 19 октября в 09:00. Возьмите ноутбуки, будет небольшой SQL-запрос.", None, None),
            (64, "STUDENT_10", "student", "Нужен свой PostgreSQL или дадут готовую базу?", 63, None),
            (65, "TEACHER_3", "teacher", "Базу дадим. Локально ставить ничего не нужно.", 64, None),
            (73, "STUDENT_11", "student", "В методичке прошлого года второй этап был до 20 октября. Это актуально?", None, None),
            (74, "TEACHER_3", "teacher", "Нет, актуален срок из этого чата: второй этап до 16 октября.", 73, None),
        ],
        "questions": [
            ("Когда сдавать первый этап курсовой по моделям данных?", [5, 22]),
            ("Что нужно для первого этапа курсовой?", [5, 7]),
            ("Когда сдавать второй этап курсовой?", [20, 22]),
            ("Можно ли первый этап сдать 16 октября?", [22]),
            ("Какой окончательный срок ЛР2 по моделям данных?", [36]),
            ("Почему для ЛР2 называли 7 октября?", [35, 36]),
            ("Можно ли взять интернет-магазин для ЛР2 по моделям?", [50]),
            ("Когда РК по моделям данных?", [63]),
            ("Нужно ли устанавливать PostgreSQL для РК?", [65]),
            ("Какой срок второго этапа актуален: из старой методички или из чата?", [74]),
            ("Какой минимальный объём курсовой в страницах?", []),
            ("Какой преподаватель принимает ЛР3 по моделям?", []),
        ],
    },
}

FILLERS = [
    "Кто-нибудь разобрался с темой «{topic}»? Не получается повторить пример из лекции.",
    "По теме «{topic}» у меня результат не совпал с примером. Вечером перепроверю.",
    "На паре разбирали тему «{topic}», а запись у меня оборвалась. Кто помнит пример?",
    "Спасибо за объяснение темы «{topic}», теперь стало понятнее.",
    "В конспекте по теме «{topic}» две разные формулировки. Надо сверить с записью.",
    "На тему «{topic}» сегодня времени не хватило, после работы посмотрю.",
    "Кто-нибудь проверял пример по теме «{topic}» на маленьких данных?",
    "У меня вопрос по теме «{topic}»: расчёт не сходится на последнем шаге.",
    "Казалось, что тема «{topic}» понятна, но на практике опять появились вопросы.",
    "Можно после пары пять минут обсудить тему «{topic}»?",
    "В материалах по теме «{topic}» ссылка на прошлогодний файл. Это нормально?",
    "В моём решении по теме «{topic}» оказалась опечатка. Теперь всё сходится.",
    "Кому-нибудь пригодилась запись лекции по теме «{topic}»?",
    "Мне кажется, в презентации по теме «{topic}» пропущен один шаг.",
    "Мои заметки по теме «{topic}» лежат в общей папке, если кому-то нужны.",
]

SOCIAL = [
    "Ребят, кто-нибудь идёт сегодня в столовую после второй пары?",
    "Автобус застрял в пробке, буду через десять минут 🙈",
    "Кто оставил кружку в 305-й? Она уже третий день там живёт.",
    "В кофейном автомате снова закончились стаканчики, берите свои.",
    "А фотки с посвящения кто-нибудь выложит?",
    "Спасибо за вчерашние конспекты! С меня кофе ☕",
    "Где сегодня встречаемся после пар?",
    "У окна лежит чёрная флешка. Заберу с собой и отдам после лекции.",
    "Погода сегодня как в ноябре, а ведь ещё сентябрь.",
    "Мне кажется, кот у входа уже знает расписание лучше нас.",
    "Кто-нибудь смотрел вчерашнюю игру? Концовка вообще неожиданная.",
    "Скиньте, пожалуйста, фото доски с прошлой пары, у меня всё смазано.",
    "Ой, не в тот чат 😅",
    "У кого зарядка для ноутбука с круглым штекером? На полчаса бы.",
    "Ребят, кто оставил пакет в аудитории? Унесли на вахту.",
    "Я сегодня без интернета, если что срочное — звоните.",
    "Всем спасибо, было весело вчера!",
    "Кто умеет чинить принтер? Он опять жуёт бумагу.",
    "Перерыв между парами сегодня двадцать минут или десять?",
    "Ахах, мем про дедлайны очень вовремя.",
]

SOCIAL_VARIANTS = [
    "Кто-нибудь видел {thing} в {place}? Не могу найти с утра.",
    "В {place} сегодня опять забыли {thing}. Кажется, это уже традиция.",
    "Если будете в {place}, поищите, пожалуйста, {thing}.",
]
PLACES = ["библиотеке", "третьей аудитории", "коридоре у деканата", "читальном зале",
          "холле", "компьютерном классе", "лаборатории", "аудитории 305"]
THINGS = ["синюю тетрадь", "переходник", "папку с распечатками", "термокружку",
          "чёрный пенал", "зарядку", "зонт", "флешку"]
NAMES = {**{f"STUDENT_{n}": name for n, name in enumerate(
    ["Аня", "Илья", "Маша", "Дима", "Лена", "Кирилл", "Оля", "Саша",
     "Катя", "Тимур", "Ника", "Паша"], 1)},
    "STAROSTA": "Арина", "TEACHER_1": "Ирина Викторовна",
    "TEACHER_2": "Сергей Павлович", "TEACHER_3": "Марина Олеговна"}


def social_pool() -> list[str]:
    pool = list(SOCIAL)
    for template in SOCIAL_VARIANTS:
        for place in PLACES:
            for thing in THINGS:
                pool.append(template.format(place=place, thing=thing))
    RNG.shuffle(pool)
    return pool


def generate() -> tuple[dict[str, list[Message]], list[dict]]:
    chat = "synthetic_group"
    drafts = []
    question_drafts = []
    social = social_pool()
    used_filler = set()
    for source, spec in CHAT_DATA.items():
        events = {e[0]: e for e in spec["events"]}
        previous = None
        for n in range(1, 91):
            old_id = f"{source}:{n}"
            day, slot = divmod(n - 1, 6)
            ts = START + timedelta(days=day, hours=slot * 2,
                                   minutes=(0 if source == "synthetic_elektro" else
                                            15 if source == "synthetic_algo" else 30) + RNG.randrange(0, 15))
            if n in events:
                _, author, role, text, reply, filename = events[n]
            else:
                role = "student"
                author = f"STUDENT_{RNG.randrange(1, 13)}"
                topic = RNG.choice(spec["topics"])
                if RNG.random() < 0.25:
                    text = social.pop()
                else:
                    options = [template.format(topic=topic) for template in FILLERS]
                    text = next((candidate for candidate in RNG.sample(options, len(options))
                                 if candidate not in used_filler), options[0])
                    used_filler.add(text)
                reply = previous if RNG.random() < 0.18 else None
                filename = None
            drafts.append((ts, old_id, author, role, text,
                           f"{source}:{reply}" if reply else None, filename))
            previous = n
        for query, ids in spec["questions"]:
            question_drafts.append((query, [f"{source}:{n}" for n in ids]))

    # Independent chatter is interleaved throughout the whole semester, not
    # confined to a separate block that retrieval could trivially ignore.
    for n in range(120):
        ts = START + timedelta(days=RNG.randrange(15), hours=RNG.randrange(0, 12),
                               minutes=RNG.randrange(60))
        drafts.append((ts, f"social:{n}", f"STUDENT_{RNG.randrange(1, 13)}",
                       "student", social.pop(), None, None))
    drafts.sort(key=lambda item: (item[0], item[1]))
    ids = {old_id: f"{chat}:{n}" for n, (_, old_id, *_) in enumerate(drafts, 1)}
    messages = []
    for ts, old_id, author, role, body, reply, filename in drafts:
        mid = ids[old_id]
        attachments = []
        if filename:
            content = f"Fictional study handout: {filename}. No real personal data.\n"
            attachments = [AttachedFile(id=f"{mid}:f1", msg_id=mid, name=filename,
                                        ext="txt", size_bytes=len(content.encode("utf-8")),
                                        path=f"files/{filename}")]
        messages.append(Message(id=mid, chat=chat, ts=ts.isoformat(timespec="seconds"),
                                author=NAMES[author], role=role, text=body,
                                reply_to=ids.get(reply),
                                src=f"synthetic.html#message{mid.split(':')[1]}",
                                attachments=attachments))
    gold = [{"query": query, "chat": chat,
             "relevant_msg_ids": [ids[old_id] for old_id in relevant]}
            for query, relevant in question_drafts]
    return {chat: messages}, gold


def main() -> None:
    chats, gold = generate()
    gold_path = ROOT / "data" / "labels" / "search_gold.jsonl"
    existing = [ROOT / "data" / "clean" / f"{chat}.jsonl" for chat in chats]
    existing.append(gold_path)
    if any(path.exists() for path in existing):
        raise SystemExit("Refusing to overwrite existing data: " +
                         ", ".join(str(path) for path in existing if path.exists()))
    for chat, messages in chats.items():
        path = ROOT / "data" / "clean" / f"{chat}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(m.model_dump_json() + "\n" for m in messages), encoding="utf-8")
        for m in messages:
            for f in m.attachments:
                target = ROOT / "data" / "raw" / chat / f.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f"Fictional study handout: {f.name}. No real personal data.\n".encode("utf-8"))
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    gold_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in gold), encoding="utf-8")
    print(f"Generated {sum(map(len, chats.values()))} fictional messages in {len(chats)} chats and {len(gold)} gold questions")


if __name__ == "__main__":
    main()
