"""Генератор тестового набора файлов для эксперимента Precision@5.

Генерирует 50 файлов с именами, НЕ совпадающими с содержимым —
чтобы точный поиск по имени был неинформативен, а семантический работал.

Набор:
  20 изображений (рисуем синтетические сцены через PIL.ImageDraw)
  15 документов (5 PDF, 5 DOCX, 5 TXT)
  15 прочих   (10 таблиц CSV/XLSX, 5 других)

Файлы сохраняются в ./test_dataset/. Имена — нейтральные IMG_NNNN,
FILE_NNNN, чтобы подстрочный поиск по имени не мог угадать содержимое.
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

# Сид фиксированный — набор детерминированный, эксперимент воспроизводим.
random.seed(42)


# --- Изображения --------------------------------------------------------

def _generate_images(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 20 синтетических картинок. Возвращает [(filename, описание)].

    Описание — что на картинке. Используется при составлении queries.json
    как ground truth: для запроса «закат на море» релевантны все картинки,
    в описании которых есть и закат, и море.
    """
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    # (описание, функция-рисователь). Рисователи простые, но дают SigLIP
    # достаточно сигнала: композиция цветов + текстовая надпись на картинке,
    # которую потом прочтёт OCR.
    scenes = [
        ("закат на море", _draw_sunset_sea),
        ("кот у окна", _draw_cat_window),
        ("горный пейзаж с озером", _draw_mountain_lake),
        ("чашка кофе на столе", _draw_coffee_cup),
        ("ночной город с огнями", _draw_night_city),
        ("букет цветов в вазе", _draw_flowers_vase),
        ("лесная тропа осенью", _draw_forest_path),
        ("снежные горные вершины", _draw_snowy_peaks),
        ("собака играет на траве", _draw_dog_grass),
        ("пляж с пальмами", _draw_beach_palms),
        ("меню кофейни с ценами", _draw_cafe_menu),
        ("красная машина на дороге", _draw_red_car),
        ("библиотека с книгами", _draw_library),
        ("звёздное небо над полем", _draw_starry_sky),
        ("детский рисунок радуги", _draw_rainbow),
        ("тарелка с едой в ресторане", _draw_food_plate),
        ("офисный стол с ноутбуком", _draw_office_desk),
        ("зимний парк со снегом", _draw_winter_park),
        ("цветущая сакура весной", _draw_sakura),
        ("водопад в джунглях", _draw_waterfall),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, draw_fn) in enumerate(scenes, start=1):
        filename = f"IMG_{i:04d}.png"
        path = out_dir / filename
        img = Image.new("RGB", (400, 300), "white")
        draw = ImageDraw.Draw(img)
        draw_fn(draw, font)
        img.save(path)
        results.append((filename, description))
    return results


# Каждая функция рисования намеренно простая: несколько заливок + текст.
# SigLIP достаточно цветовой композиции и семантики OCR-текста.

def _draw_sunset_sea(d, font):
    d.rectangle([0, 0, 400, 150], fill=(255, 140, 60))  # небо оранжевое
    d.rectangle([0, 150, 400, 300], fill=(40, 80, 120))  # море синее
    d.ellipse([160, 100, 240, 180], fill=(255, 220, 100))  # солнце
    d.text((10, 10), "Sunset over the sea", fill="black", font=font)


def _draw_cat_window(d, font):
    d.rectangle([0, 0, 400, 300], fill=(200, 220, 240))
    d.rectangle([100, 50, 300, 250], outline="black", width=3)  # рама окна
    d.line([200, 50, 200, 250], fill="black", width=2)
    d.ellipse([170, 180, 230, 240], fill=(120, 100, 80))  # кот (силуэт)
    d.text((10, 10), "Cat sitting by the window", fill="black", font=font)


def _draw_mountain_lake(d, font):
    d.rectangle([0, 0, 400, 150], fill=(180, 210, 230))  # небо
    d.polygon([(50, 150), (150, 40), (250, 150)], fill=(120, 120, 140))  # гора
    d.polygon([(200, 150), (300, 60), (400, 150)], fill=(100, 100, 120))
    d.rectangle([0, 150, 400, 300], fill=(80, 130, 160))  # озеро
    d.text((10, 10), "Mountain lake landscape", fill="black", font=font)


def _draw_coffee_cup(d, font):
    d.rectangle([0, 0, 400, 300], fill=(230, 210, 190))  # стол
    d.ellipse([150, 130, 250, 230], fill="white", outline="black", width=3)
    d.ellipse([165, 145, 235, 215], fill=(80, 50, 30))  # кофе
    d.text((10, 10), "Cup of coffee on the table", fill="black", font=font)


def _draw_night_city(d, font):
    d.rectangle([0, 0, 400, 200], fill=(20, 20, 50))  # ночное небо
    d.rectangle([0, 200, 400, 300], fill=(10, 10, 30))
    for x in range(20, 380, 40):
        d.rectangle([x, 100, x + 30, 250], fill=(50, 50, 80))
    for x in range(30, 380, 20):
        for y in range(120, 240, 20):
            d.rectangle([x, y, x + 5, y + 5], fill=(255, 255, 150))
    d.text((10, 10), "Night city with lights", fill="white", font=font)


def _draw_flowers_vase(d, font):
    d.rectangle([0, 0, 400, 300], fill=(240, 230, 210))
    d.rectangle([170, 200, 230, 280], fill=(100, 150, 200))  # ваза
    for cx, cy, color in [(180, 120, (255, 100, 100)), (200, 100, (255, 200, 100)),
                          (220, 130, (200, 100, 200)), (190, 150, (255, 150, 200))]:
        d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill=color)
    d.text((10, 10), "Bouquet of flowers in a vase", fill="black", font=font)


def _draw_forest_path(d, font):
    d.rectangle([0, 0, 400, 300], fill=(180, 150, 80))  # осенний фон
    for x in [50, 120, 280, 350]:
        d.rectangle([x, 80, x + 20, 250], fill=(80, 50, 30))  # стволы
        d.ellipse([x - 30, 40, x + 50, 120], fill=(220, 140, 40))  # крона осень
    d.polygon([(150, 300), (250, 300), (220, 100)], fill=(140, 110, 70))  # тропа
    d.text((10, 10), "Forest path in autumn", fill="black", font=font)


def _draw_snowy_peaks(d, font):
    d.rectangle([0, 0, 400, 150], fill=(200, 220, 240))
    d.polygon([(0, 200), (100, 50), (200, 200)], fill=(220, 220, 230))
    d.polygon([(150, 200), (250, 30), (350, 200)], fill=(200, 200, 220))
    d.polygon([(100, 50), (130, 80), (70, 80)], fill="white")  # снег на вершине
    d.polygon([(250, 30), (280, 60), (220, 60)], fill="white")
    d.text((10, 10), "Snowy mountain peaks", fill="black", font=font)


def _draw_dog_grass(d, font):
    d.rectangle([0, 0, 400, 150], fill=(150, 200, 230))
    d.rectangle([0, 150, 400, 300], fill=(80, 170, 80))  # трава
    d.ellipse([170, 180, 250, 230], fill=(180, 130, 80))  # тело
    d.ellipse([240, 170, 290, 210], fill=(180, 130, 80))  # голова
    d.text((10, 10), "Dog playing on the grass", fill="black", font=font)


def _draw_beach_palms(d, font):
    d.rectangle([0, 0, 400, 150], fill=(180, 220, 240))
    d.rectangle([0, 150, 400, 220], fill=(80, 160, 200))  # море
    d.rectangle([0, 220, 400, 300], fill=(230, 210, 160))  # пляж
    for x in [60, 320]:
        d.rectangle([x, 100, x + 15, 230], fill=(100, 70, 40))
        d.ellipse([x - 40, 60, x + 55, 120], fill=(80, 160, 60))
    d.text((10, 10), "Beach with palm trees", fill="black", font=font)


def _draw_cafe_menu(d, font):
    d.rectangle([0, 0, 400, 300], fill=(250, 245, 230))
    d.text((20, 20), "MENU", fill="black", font=font)
    d.text((20, 60), "Espresso - 150 rub", fill="black", font=font)
    d.text((20, 90), "Cappuccino - 200 rub", fill="black", font=font)
    d.text((20, 120), "Latte - 220 rub", fill="black", font=font)
    d.text((20, 150), "Americano - 170 rub", fill="black", font=font)
    d.text((20, 180), "Croissant - 120 rub", fill="black", font=font)


def _draw_red_car(d, font):
    d.rectangle([0, 0, 400, 200], fill=(180, 200, 220))
    d.rectangle([0, 200, 400, 300], fill=(80, 80, 80))  # дорога
    d.rectangle([100, 150, 300, 220], fill=(200, 40, 40))  # корпус
    d.rectangle([130, 120, 270, 170], fill=(150, 30, 30))  # крыша
    d.ellipse([120, 200, 170, 250], fill="black")  # колёса
    d.ellipse([230, 200, 280, 250], fill="black")
    d.text((10, 10), "Red car on the road", fill="black", font=font)


def _draw_library(d, font):
    d.rectangle([0, 0, 400, 300], fill=(160, 130, 100))
    colors = [(200, 40, 40), (40, 100, 200), (40, 150, 80), (200, 180, 40), (150, 80, 200)]
    for row in range(3):
        for i in range(10):
            c = colors[(row * 10 + i) % len(colors)]
            d.rectangle([20 + i * 36, 50 + row * 80, 50 + i * 36, 120 + row * 80], fill=c)
    d.text((10, 10), "Library full of books", fill="white", font=font)


def _draw_starry_sky(d, font):
    d.rectangle([0, 0, 400, 250], fill=(10, 10, 40))
    d.rectangle([0, 250, 400, 300], fill=(40, 80, 30))
    for _ in range(80):
        x, y = random.randint(0, 400), random.randint(0, 250)
        d.ellipse([x, y, x + 2, y + 2], fill="white")
    d.text((10, 10), "Starry sky over the field", fill="white", font=font)


def _draw_rainbow(d, font):
    d.rectangle([0, 0, 400, 300], fill=(200, 230, 250))
    colors = [(200, 40, 40), (240, 140, 40), (250, 230, 60),
              (100, 200, 80), (60, 120, 220), (130, 60, 180)]
    for i, c in enumerate(colors):
        d.arc([50 + i * 10, 100 + i * 10, 350 - i * 10, 400 - i * 10],
              180, 360, fill=c, width=10)
    d.text((10, 10), "Children's drawing of a rainbow", fill="black", font=font)


def _draw_food_plate(d, font):
    d.rectangle([0, 0, 400, 300], fill=(220, 200, 180))
    d.ellipse([80, 80, 320, 280], fill="white", outline="black", width=2)
    d.ellipse([140, 130, 200, 180], fill=(220, 180, 80))  # картошка
    d.ellipse([200, 140, 260, 190], fill=(160, 60, 40))  # мясо
    d.ellipse([170, 190, 230, 230], fill=(60, 140, 60))  # зелень
    d.text((10, 10), "Plate with food at the restaurant", fill="black", font=font)


def _draw_office_desk(d, font):
    d.rectangle([0, 0, 400, 200], fill=(230, 220, 210))
    d.rectangle([0, 200, 400, 300], fill=(180, 140, 100))  # стол
    d.rectangle([100, 120, 300, 220], fill=(50, 50, 50))  # ноутбук
    d.rectangle([110, 130, 290, 210], fill=(100, 150, 200))  # экран
    d.rectangle([320, 200, 370, 230], fill="white")  # бумага
    d.text((10, 10), "Office desk with laptop", fill="black", font=font)


def _draw_winter_park(d, font):
    d.rectangle([0, 0, 400, 300], fill=(220, 230, 240))
    d.rectangle([0, 220, 400, 300], fill="white")  # снег
    for x in [80, 180, 280]:
        d.rectangle([x, 120, x + 15, 230], fill=(80, 50, 30))
        d.polygon([(x - 20, 180), (x + 35, 180), (x + 7, 100)], fill="white")
    d.text((10, 10), "Winter park covered in snow", fill="black", font=font)


def _draw_sakura(d, font):
    d.rectangle([0, 0, 400, 300], fill=(200, 230, 240))
    d.rectangle([180, 150, 210, 300], fill=(80, 50, 30))
    for _ in range(30):
        cx, cy = random.randint(80, 320), random.randint(30, 180)
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(255, 180, 210))
    d.text((10, 10), "Sakura cherry blossom in spring", fill="black", font=font)


def _draw_waterfall(d, font):
    d.rectangle([0, 0, 400, 300], fill=(50, 120, 60))  # джунгли
    d.rectangle([150, 50, 250, 250], fill=(180, 220, 240))  # вода
    for y in range(60, 250, 20):
        d.line([(150, y), (250, y + 10)], fill="white", width=2)
    d.ellipse([130, 240, 270, 280], fill=(200, 230, 250))  # брызги
    d.text((10, 10), "Waterfall in the jungle", fill="white", font=font)


# --- Документы ----------------------------------------------------------

def _generate_pdfs(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 PDF с разными темами."""
    import fitz  # PyMuPDF

    topics = [
        ("договор аренды квартиры между арендодателем и арендатором на срок 11 месяцев",
         "Договор аренды жилого помещения. Арендодатель передаёт арендатору во временное "
         "пользование квартиру по адресу Москва. Срок аренды — 11 месяцев. Ежемесячная плата "
         "составляет 50000 рублей и вносится до 5 числа. Коммунальные платежи оплачиваются "
         "арендатором отдельно. Залог возвращается при расторжении."),
        ("научная статья о машинном обучении и нейронных сетях",
         "В работе рассматриваются современные архитектуры глубоких нейронных сетей. "
         "Трансформеры показали превосходство над рекуррентными моделями в задачах "
         "обработки естественного языка. Механизм внимания позволяет учитывать "
         "контекст всей последовательности. Обучение проводилось на датасете ImageNet."),
        ("рецепт приготовления борща с мясом и сметаной",
         "Классический рецепт борща. Ингредиенты: свёкла, капуста, морковь, лук, "
         "картофель, говядина, томатная паста. Варить бульон на костях 2 часа. "
         "Обжарить овощи на сковороде. Добавить свёклу в конце варки. "
         "Подавать со сметаной и зеленью."),
        ("инструкция по технике безопасности на производстве",
         "Требования охраны труда для работников цеха. Запрещено приступать к работе "
         "без средств индивидуальной защиты. При работе со станками обязательны очки "
         "и перчатки. В случае травмы немедленно сообщить руководителю. "
         "Эвакуационные выходы должны быть свободны."),
        ("отчёт о финансовых результатах компании за квартал",
         "Выручка за третий квартал составила 150 миллионов рублей, что на 12 процентов "
         "выше аналогичного периода прошлого года. Чистая прибыль выросла до 22 миллионов. "
         "Основной вклад внесли продажи в регионах. Инвестиции в маркетинг окупились."),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, body) in enumerate(topics, start=1):
        filename = f"FILE_{i:04d}.pdf"
        path = out_dir / filename
        doc = fitz.open()
        page = doc.new_page()
        # insertText ставит текст в позицию; шрифт по умолчанию Helvetica,
        # кириллицу он НЕ поддерживает — используем Cyrillic-совместимый шрифт.
        # PyMuPDF встроенных кириллических шрифтов не имеет, поэтому
        # используем htmlbox для рендера UTF-8 текста.
        rect = fitz.Rect(50, 50, 550, 800)
        page.insert_htmlbox(rect, f"<p>{body}</p>")
        doc.save(str(path))
        doc.close()
        results.append((filename, description))
    return results


def _generate_docx_files(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 DOCX."""
    import docx

    topics = [
        ("резюме программиста Python с опытом 5 лет",
         "Резюме. Иванов Иван. Должность: Python-разработчик. Опыт 5 лет. "
         "Стек: Django, FastAPI, PostgreSQL, Redis. Участвовал в разработке "
         "высоконагруженных сервисов. Знаю Docker и Kubernetes. "
         "Английский Intermediate."),
        ("план маркетинговой кампании на летний сезон",
         "Маркетинговый план. Цель — увеличение продаж летом на 30 процентов. "
         "Каналы: социальные сети, таргетированная реклама, email-рассылки. "
         "Основная аудитория — молодёжь 18–25 лет. Бюджет 500 тысяч рублей. "
         "KPI: охват, конверсия, средний чек."),
        ("дипломная работа по биологии о поведении млекопитающих",
         "Введение. Изучение поведения млекопитающих в естественной среде обитания "
         "позволяет понять механизмы адаптации. Объект исследования — лисы "
         "в подмосковных лесах. Наблюдения проводились с марта по сентябрь. "
         "Выводы: лисы проявляют социальное поведение чаще, чем считалось."),
        ("протокол собрания совета директоров о стратегии",
         "Протокол заседания. Повестка: утверждение стратегии на 2025 год. "
         "Присутствовали все члены совета. Решили: инвестировать в новое "
         "производство, открыть филиал в Казани, запустить обучающую программу. "
         "Следующее заседание в марте."),
        ("статья о здоровом питании и правильной диете",
         "Правильное питание основано на балансе белков, жиров и углеводов. "
         "Рекомендуется употреблять овощи и фрукты ежедневно. Избегать избытка "
         "сахара и трансжиров. Пить достаточно воды. Ужин должен быть лёгким "
         "и за 3 часа до сна."),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, body) in enumerate(topics, start=6):
        filename = f"FILE_{i:04d}.docx"
        path = out_dir / filename
        d = docx.Document()
        for paragraph in body.split(". "):
            if paragraph.strip():
                d.add_paragraph(paragraph.strip())
        d.save(str(path))
        results.append((filename, description))
    return results


def _generate_txt_files(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 TXT."""
    topics = [
        ("список покупок в магазине продукты",
         "хлеб\nмолоко\nяйца\nсыр\nкурица\nовощи\nфрукты\nмасло\nрис\nсоль"),
        ("стихотворение о природе и временах года",
         "Осенний лес прощается с листвой,\n"
         "Шуршат дорожки под ногой усталой.\n"
         "Зима придёт со снежной тишиной,\n"
         "Накроет землю пеленою талой."),
        ("заметки с лекции по философии",
         "Декарт: мыслю следовательно существую. Рационализм.\n"
         "Кант: вещь в себе непознаваема. Критика чистого разума.\n"
         "Ницше: воля к власти. Сверхчеловек.\n"
         "Сартр: существование предшествует сущности."),
        ("инструкция как настроить роутер дома",
         "1. Подключите кабель провайдера к порту WAN.\n"
         "2. Включите роутер в сеть. Подождите 30 секунд.\n"
         "3. Откройте в браузере 192.168.1.1.\n"
         "4. Введите логин и пароль admin.\n"
         "5. Настройте параметры PPPoE от провайдера."),
        ("дневниковая запись о путешествии в горы",
         "Утро встретило нас туманом в долине. Поднялись на перевал за четыре часа. "
         "Вид с вершины захватывает дух. Ночевали в палатке у озера. "
         "Звёздное небо без засветки — невероятное зрелище."),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, body) in enumerate(topics, start=11):
        filename = f"FILE_{i:04d}.txt"
        path = out_dir / filename
        path.write_text(body, encoding="utf-8")
        results.append((filename, description))
    return results


# --- Таблицы ------------------------------------------------------------

def _generate_csv_files(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 CSV."""
    datasets = [
        ("таблица продаж по регионам за год",
         ["регион", "продажи", "менеджер", "квартал"],
         [["Москва", "1500000", "Петров", "Q1"],
          ["Санкт-Петербург", "980000", "Сидоров", "Q1"],
          ["Казань", "450000", "Иванова", "Q2"],
          ["Новосибирск", "320000", "Кузнецов", "Q2"]]),
        ("список сотрудников компании с зарплатами",
         ["имя", "должность", "отдел", "зарплата"],
         [["Анна Смирнова", "дизайнер", "креатив", "80000"],
          ["Иван Петров", "разработчик", "IT", "150000"],
          ["Мария Козлова", "менеджер", "продажи", "90000"]]),
        ("каталог товаров интернет-магазина электроники",
         ["название", "категория", "цена", "наличие"],
         [["iPhone 15", "смартфоны", "95000", "да"],
          ["MacBook Pro", "ноутбуки", "210000", "да"],
          ["AirPods Pro", "наушники", "25000", "нет"]]),
        ("статистика посещений сайта по месяцам",
         ["месяц", "посещения", "уникальные", "отказы"],
         [["январь", "15000", "8500", "32"],
          ["февраль", "17500", "9200", "28"],
          ["март", "22000", "11000", "25"]]),
        ("рейтинг книг по жанрам с оценками",
         ["название", "автор", "жанр", "оценка"],
         [["Мастер и Маргарита", "Булгаков", "роман", "4.8"],
          ["1984", "Оруэлл", "антиутопия", "4.7"],
          ["Гарри Поттер", "Роулинг", "фэнтези", "4.6"]]),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, header, rows) in enumerate(datasets, start=16):
        filename = f"FILE_{i:04d}.csv"
        path = out_dir / filename
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        results.append((filename, description))
    return results


def _generate_xlsx_files(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 XLSX."""
    import openpyxl

    datasets = [
        ("бюджет семьи на месяц по категориям расходов",
         "Бюджет",
         [["категория", "планируемое", "фактическое"],
          ["продукты", "20000", "22500"],
          ["транспорт", "5000", "4800"],
          ["развлечения", "10000", "8200"],
          ["коммунальные", "7000", "7000"]]),
        ("расписание занятий в университете на семестр",
         "Расписание",
         [["день", "время", "предмет", "аудитория"],
          ["понедельник", "9:00", "математический анализ", "101"],
          ["вторник", "10:30", "физика", "205"],
          ["среда", "9:00", "программирование", "310"]]),
        ("инвентаризация склада по позициям и количеству",
         "Склад",
         [["артикул", "наименование", "количество", "цена"],
          ["A-001", "болты М8", "500", "15"],
          ["A-002", "гайки М8", "450", "8"],
          ["B-101", "шурупы 3мм", "1200", "5"]]),
        ("план тренировок в тренажёрном зале по дням",
         "Тренировки",
         [["день", "упражнение", "подходы", "повторения"],
          ["понедельник", "приседания", "4", "12"],
          ["среда", "жим лёжа", "4", "10"],
          ["пятница", "становая тяга", "3", "8"]]),
        ("данные клиентов с контактами и суммой покупок",
         "Клиенты",
         [["имя", "телефон", "email", "сумма"],
          ["Алексей Иванов", "+79001234567", "alex@mail.ru", "45000"],
          ["Ольга Петрова", "+79007654321", "olga@mail.ru", "32000"]]),
    ]

    results: list[tuple[str, str]] = []
    for i, (description, sheet_name, rows) in enumerate(datasets, start=21):
        filename = f"FILE_{i:04d}.xlsx"
        path = out_dir / filename
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        for row in rows:
            ws.append(row)
        wb.save(str(path))
        results.append((filename, description))
    return results


# --- Прочие файлы -------------------------------------------------------

def _generate_other_files(out_dir: Path) -> list[tuple[str, str]]:
    """Генерирует 5 файлов неизвестных типов (индексируются по имени).

    Имена ОСМЫСЛЕННЫЕ (в отличие от IMG_NNNN для картинок), потому что
    fallback-обработка индексирует именно имя. Это согласуется с
    назначением теста: показать, что даже для прочих файлов семантика
    работает на уровне имени.
    """
    names = [
        ("конфигурация виртуальной_машины_ubuntu.conf",
         "настройки виртуальной машины ubuntu"),
        ("бекап_базы_данных_2024_декабрь.dump",
         "резервная копия базы данных за декабрь 2024"),
        ("архив_фотографий_отпуск_турция.tar",
         "архив фотографий с отпуска в турции"),
        ("лог_сервера_nginx_ошибки.log",
         "файл логов веб-сервера nginx с ошибками"),
        ("презентация_проекта_стартап.key",
         "презентация стартап-проекта в формате keynote"),
    ]

    results: list[tuple[str, str]] = []
    for name, description in names:
        path = out_dir / name
        # Кладём пустой (но не нулевого размера) файл — indexer требует size > 0.
        path.write_bytes(b"binary\x00data\x00placeholder")
        results.append((name, description))
    return results


# --- Главный оркестратор ------------------------------------------------

def generate(out_dir: Path) -> list[dict]:
    """Генерирует весь набор. Возвращает манифест — список словарей
    с filename / description / type для последующей разметки queries."""
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []
    for filename, desc in _generate_images(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "image"})
    for filename, desc in _generate_pdfs(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "pdf"})
    for filename, desc in _generate_docx_files(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "docx"})
    for filename, desc in _generate_txt_files(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "txt"})
    for filename, desc in _generate_csv_files(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "csv"})
    for filename, desc in _generate_xlsx_files(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "xlsx"})
    for filename, desc in _generate_other_files(out_dir):
        manifest.append({"filename": filename, "description": desc, "type": "other"})
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Генерация тестового набора файлов")
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).parent / "test_dataset",
        help="Директория для сохранения набора",
    )
    args = parser.parse_args()

    manifest = generate(args.out)

    # Сохраняем манифест рядом с датасетом для справки. queries.json
    # создаётся отдельно руками — с ground truth разметкой.
    import json
    (args.out / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Сгенерировано {len(manifest)} файлов в {args.out}")


if __name__ == "__main__":
    main()
