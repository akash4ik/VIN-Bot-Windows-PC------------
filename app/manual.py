"""In-bot manuals: a worker guide and an administrator guide.

Both manuals are plain text pages without codes, file names or technical
settings, so anybody can read them on a phone. Every page is short, uses one
idea per line and large emoji markers, which keeps the text readable even with
poor eyesight. The pages are shown one by one with navigation buttons.
"""

from __future__ import annotations

from app.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t

WORKER = "worker"
ADMIN = "admin"

TITLES: dict[str, dict[str, str]] = {
    WORKER: {"ru": "ИНСТРУКЦИЯ", "de": "ANLEITUNG"},
    ADMIN: {"ru": "ИНСТРУКЦИЯ АДМИНИСТРАТОРА", "de": "ANLEITUNG FÜR ADMINISTRATOREN"},
}

RU_WORKER: tuple[str, ...] = (
    # 1 — contents
    (
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Бот помогает вести учёт автомобилей:\n"
        "карточки, поиск по VIN\n"
        "и раздел «🎨 Покраска».\n\n"
        "<b>Что внутри:</b>\n\n"
        "1️⃣ Карточка автомобиля\n"
        "2️⃣ Проверка VIN\n"
        "3️⃣ Поиск по VIN\n"
        "4️⃣ Покраска: сдаём машину\n"
        "5️⃣ Покраска: забираем машину\n"
        "6️⃣ Правила фотографий\n"
        "7️⃣ Правила ввода\n"
        "8️⃣ Если что-то не так"
    ),
    # 2 — vehicle card
    (
        "🚗 <b>КАРТОЧКА АВТОМОБИЛЯ</b>\n\n"
        "Карточка — это автомобиль\n"
        "с фотографией, накладной и VIN.\n\n"
        "<b>Как создать:</b>\n\n"
        "1️⃣ Нажмите\n"
        "«➕ Создать карточку».\n\n"
        "2️⃣ Отправьте фото автомобиля.\n\n"
        "3️⃣ Отправьте фото\n"
        "полной накладной.\n\n"
        "4️⃣ Отправьте фото с VIN.\n"
        "Это может быть крупный\n"
        "фрагмент таблички,\n"
        "а может — та же накладная\n"
        "целиком: бот найдёт код сам.\n\n"
        "💡 Фото автомобиля и накладной\n"
        "должны быть разными.\n\n"
        "💡 Копия фотографий сразу\n"
        "сохраняется в архив бота,\n"
        "поэтому они не потеряются."
    ),
    # 3 — VIN check
    (
        "🔢 <b>ПРОВЕРКА VIN</b>\n\n"
        "После третьего фото бот покажет\n"
        "распознанные символы.\n\n"
        "<b>Что делать:</b>\n\n"
        "• Сверьте все символы с фото.\n\n"
        "• Всё верно — нажмите\n"
        "«✅ Всё верно».\n\n"
        "• Ошибка — нажмите\n"
        "«✏️ Исправить VIN»\n"
        "и введите символы вручную.\n\n"
        "• Плохое фото — нажмите\n"
        "«📷 Переснять VIN».\n\n"
        "⚠️ Сохраняйте только\n"
        "проверенный VIN: по ошибке\n"
        "карточку потом не найти."
    ),
    # 4 — search
    (
        "🔎 <b>ПОИСК ПО VIN</b>\n\n"
        "1️⃣ Нажмите «🔎 Найти по VIN».\n\n"
        "2️⃣ Введите последние 4\n"
        "или 6 символов VIN.\n\n"
        "Вместо этого можно отправить\n"
        "фото VIN — бот прочитает его сам.\n\n"
        "<b>В результатах:</b>\n\n"
        "• стрелки — листать карточки;\n\n"
        "• «📄 Накладная» — открыть\n"
        "накладную целиком;\n\n"
        "• «🚗 Фото автомобиля» —\n"
        "вернуться к фото.\n\n"
        "💡 Находятся ВСЕ карточки\n"
        "с такими последними символами."
    ),
    # 5 — painting, hand over
    (
        "🎨 <b>ПОКРАСКА: СДАЁМ МАШИНУ</b>\n\n"
        "1️⃣ Нажмите «🎨 Покраска».\n\n"
        "2️⃣ Нажмите\n"
        "«📥 Сдать в покраску».\n\n"
        "3️⃣ Отправьте фото автомобиля.\n\n"
        "4️⃣ Отправьте крупный\n"
        "обрезанный фрагмент VIN.\n\n"
        "5️⃣ Проверьте VIN\n"
        "и подтвердите.\n\n"
        "💡 Для покраски накладная\n"
        "НЕ нужна: только два фото."
    ),
    # 6 — painting, take back
    (
        "🎨 <b>ПОКРАСКА: ЗАБИРАЕМ МАШИНУ</b>\n\n"
        "«📋 На покраске» — машины,\n"
        "которые сейчас красят.\n\n"
        "«✅ Забранные» — машины,\n"
        "которые уже забрали.\n\n"
        "<b>Как забрать:</b>\n\n"
        "1️⃣ Откройте «📋 На покраске».\n\n"
        "2️⃣ Нажмите\n"
        "«✅ Забрали с покраски».\n\n"
        "3️⃣ Подтвердите: «Да, забрали».\n\n"
        "Машина сразу перейдёт\n"
        "в раздел «✅ Забранные».\n\n"
        "🔎 «Поиск по VIN» внутри покраски\n"
        "тоже находит машину и позволяет\n"
        "отметить выдачу."
    ),
    # 7 — photo rules
    (
        "📷 <b>ПРАВИЛА ФОТОГРАФИЙ</b>\n\n"
        "✅ Фото автомобиля\n"
        "и накладной — минимум\n"
        "320 × 240 точек.\n\n"
        "✅ Фрагмент VIN — минимум\n"
        "160 × 50 точек.\n\n"
        "✅ Размер файла — до 10 МБ.\n\n"
        "✅ Три разные фотографии:\n"
        "автомобиль, накладная, VIN.\n\n"
        "✅ В кадре VIN видны подпись\n"
        "и вся строка целиком.\n\n"
        "❌ Одно и то же фото дважды\n"
        "использовать нельзя.\n\n"
        "❌ Размытые, тёмные снимки,\n"
        "блики и обрезанные края\n"
        "не допускаются."
    ),
    # 8 — input rules
    (
        "⌨️ <b>ПРАВИЛА ВВОДА</b>\n\n"
        "✅ VIN — 17 символов\n"
        "или последние 6.\n\n"
        "✅ Поиск — последние 4\n"
        "или 6 символов.\n\n"
        "✅ Только латинские буквы\n"
        "и цифры.\n\n"
        "❌ Буквы I, O и Q\n"
        "в VIN не используются.\n\n"
        "❌ Лишний текст, пробелы\n"
        "и пояснения отклоняются.\n\n"
        "❌ Слишком длинные сообщения\n"
        "отклоняются.\n\n"
        "⚠️ Один и тот же автомобиль\n"
        "дважды не сохраняется:\n"
        "бот предупредит."
    ),
    # 9 — troubleshooting
    (
        "🆘 <b>ЕСЛИ ЧТО-ТО НЕ ТАК</b>\n\n"
        "• «Действие устарело» —\n"
        "начните заново из меню.\n\n"
        "• VIN не читается —\n"
        "переснимите крупным планом\n"
        "или введите вручную.\n\n"
        "• Ничего не находится —\n"
        "проверьте последние символы.\n\n"
        "• Нет доступа — обратитесь\n"
        "к администратору.\n\n"
        "<b>Ваши права</b> зависят от роли:\n\n"
        "🚚 водитель — карточки\n"
        "и вся покраска;\n\n"
        "👷 работник — ещё поиск\n"
        "и все карточки.\n\n"
        "💡 В любой момент нажмите\n"
        "«❌ Отмена» и начните заново."
    ),
)

DE_WORKER: tuple[str, ...] = (
    # 1 — contents
    (
        "👋 <b>Willkommen!</b>\n\n"
        "Der Bot erfasst Fahrzeuge:\n"
        "Karten, VIN-Suche\n"
        "und den Bereich „🎨 Lackierung“.\n\n"
        "<b>Inhalt:</b>\n\n"
        "1️⃣ Fahrzeugkarte\n"
        "2️⃣ VIN prüfen\n"
        "3️⃣ Nach VIN suchen\n"
        "4️⃣ Lackierung: Fahrzeug abgeben\n"
        "5️⃣ Lackierung: Fahrzeug abholen\n"
        "6️⃣ Regeln für Fotos\n"
        "7️⃣ Regeln für Eingaben\n"
        "8️⃣ Wenn etwas nicht klappt"
    ),
    # 2 — vehicle card
    (
        "🚗 <b>FAHRZEUGKARTE</b>\n\n"
        "Eine Karte besteht aus Foto,\n"
        "Beleg und VIN.\n\n"
        "<b>So wird sie angelegt:</b>\n\n"
        "1️⃣ „➕ Fahrzeug anlegen“\n"
        "drücken.\n\n"
        "2️⃣ Foto des Fahrzeugs senden.\n\n"
        "3️⃣ Foto des vollständigen\n"
        "Belegs senden.\n\n"
        "4️⃣ Separat einen großen\n"
        "VIN-Ausschnitt senden.\n\n"
        "💡 Drei UNTERSCHIEDLICHE\n"
        "Fotos sind nötig.\n\n"
        "💡 Eine Kopie der Fotos\n"
        "geht sofort ins Archiv,\n"
        "sie gehen nicht verloren."
    ),
    # 3 — VIN check
    (
        "🔢 <b>VIN PRÜFEN</b>\n\n"
        "Nach dem dritten Foto zeigt\n"
        "der Bot die erkannten Zeichen.\n\n"
        "<b>So geht es weiter:</b>\n\n"
        "• Alle Zeichen mit dem Foto\n"
        "vergleichen.\n\n"
        "• Alles richtig — „✅ Angaben\n"
        "stimmen“ drücken.\n\n"
        "• Fehler — „✏️ VIN korrigieren“\n"
        "drücken und manuell eingeben.\n\n"
        "• Schlechtes Foto — „📷 VIN neu\n"
        "fotografieren“ drücken.\n\n"
        "⚠️ Nur geprüfte VIN speichern:\n"
        "mit einem Fehler ist die Karte\n"
        "später nicht zu finden."
    ),
    # 4 — search
    (
        "🔎 <b>NACH VIN SUCHEN</b>\n\n"
        "1️⃣ „🔎 Nach VIN suchen“\n"
        "drücken.\n\n"
        "2️⃣ Die letzten 4 oder 6\n"
        "Zeichen der VIN eingeben.\n\n"
        "Stattdessen kann ein Foto der\n"
        "VIN gesendet werden — der Bot\n"
        "liest es selbst.\n\n"
        "<b>In den Treffern:</b>\n\n"
        "• Pfeile — Karten blättern;\n\n"
        "• „📄 Beleg“ — den ganzen\n"
        "Beleg öffnen;\n\n"
        "• „🚗 Fahrzeugfoto“ — zurück\n"
        "zum Foto.\n\n"
        "💡 Es werden ALLE Karten mit\n"
        "diesen Endzeichen gefunden."
    ),
    # 5 — painting, hand over
    (
        "🎨 <b>LACKIERUNG: ABGEBEN</b>\n\n"
        "1️⃣ „🎨 Lackierung“ drücken.\n\n"
        "2️⃣ „📥 In Lackierung geben“\n"
        "drücken.\n\n"
        "3️⃣ Foto des Fahrzeugs senden.\n\n"
        "4️⃣ Großen VIN-Ausschnitt\n"
        "senden.\n\n"
        "5️⃣ VIN prüfen und bestätigen.\n\n"
        "💡 Für die Lackierung ist kein\n"
        "Beleg nötig: nur zwei Fotos."
    ),
    # 6 — painting, take back
    (
        "🎨 <b>LACKIERUNG: ABHOLEN</b>\n\n"
        "„📋 In Lackierung“ — Fahrzeuge,\n"
        "die gerade lackiert werden.\n\n"
        "„✅ Abgeholt“ — Fahrzeuge,\n"
        "die bereits abgeholt sind.\n\n"
        "<b>So wird abgeholt:</b>\n\n"
        "1️⃣ „📋 In Lackierung“ öffnen.\n\n"
        "2️⃣ „✅ Aus Lackierung abgeholt“\n"
        "drücken.\n\n"
        "3️⃣ Mit „Ja, abgeholt“\n"
        "bestätigen.\n\n"
        "Das Fahrzeug wechselt sofort\n"
        "in den Bereich „✅ Abgeholt“.\n\n"
        "🔎 „Nach VIN suchen“ findet das\n"
        "Fahrzeug in der Lackierung und\n"
        "erlaubt ebenfalls die Abholung."
    ),
    # 7 — photo rules
    (
        "📷 <b>REGELN FÜR FOTOS</b>\n\n"
        "✅ Fahrzeug- und Belegfoto:\n"
        "mindestens 320 × 240 Punkte.\n\n"
        "✅ VIN-Ausschnitt: mindestens\n"
        "160 × 50 Punkte.\n\n"
        "✅ Dateigröße: bis 10 MB.\n\n"
        "✅ Drei unterschiedliche Fotos:\n"
        "Fahrzeug, Beleg, VIN.\n\n"
        "✅ Im VIN-Ausschnitt sind\n"
        "Beschriftung und die ganze\n"
        "Zeile sichtbar.\n\n"
        "❌ Dasselbe Foto darf nicht\n"
        "zweimal verwendet werden.\n\n"
        "❌ Unscharfe, dunkle Bilder,\n"
        "Spiegelungen und abgeschnittene\n"
        "Ränder sind nicht erlaubt."
    ),
    # 8 — input rules
    (
        "⌨️ <b>REGELN FÜR EINGABEN</b>\n\n"
        "✅ VIN: 17 Zeichen\n"
        "oder die letzten 6.\n\n"
        "✅ Suche: die letzten 4\n"
        "oder 6 Zeichen.\n\n"
        "✅ Nur lateinische Buchstaben\n"
        "und Zahlen.\n\n"
        "❌ I, O und Q kommen in einer\n"
        "VIN nicht vor.\n\n"
        "❌ Zusätzlicher Text,\n"
        "Leerzeichen und Erklärungen\n"
        "werden abgewiesen.\n\n"
        "❌ Zu lange Nachrichten werden\n"
        "abgewiesen.\n\n"
        "⚠️ Dasselbe Fahrzeug wird nicht\n"
        "zweimal gespeichert: der Bot\n"
        "meldet es."
    ),
    # 9 — troubleshooting
    (
        "🆘 <b>WENN ETWAS NICHT KLAPPT</b>\n\n"
        "• „Aktion abgelaufen“ —\n"
        "im Menü neu beginnen.\n\n"
        "• VIN wird nicht erkannt —\n"
        "nah und groß neu fotografieren\n"
        "oder manuell eingeben.\n\n"
        "• Nichts gefunden — die\n"
        "letzten Zeichen prüfen.\n\n"
        "• Kein Zugang — an den\n"
        "Administrator wenden.\n\n"
        "<b>Ihre Rechte</b> hängen an der\n"
        "Rolle:\n\n"
        "🚚 Fahrer — Karten anlegen\n"
        "und die ganze Lackierung;\n\n"
        "👷 Mitarbeiter — zusätzlich\n"
        "Suche und alle Karten.\n\n"
        "💡 Jederzeit „❌ Abbrechen“\n"
        "drücken und neu beginnen."
    ),
)

RU_ADMIN: tuple[str, ...] = (
    # 1 — contents
    (
        "🛡 <b>Добро пожаловать\n"
        "в админ-панель!</b>\n\n"
        "Здесь собрано всё, что доступно\n"
        "администратору\n"
        "и главному администратору.\n\n"
        "<b>Что внутри:</b>\n\n"
        "1️⃣ Админ-панель\n"
        "2️⃣ Пользователи и роли\n"
        "3️⃣ Изменение роли\n"
        "4️⃣ Переименование\n"
        "5️⃣ Удаление карточек\n"
        "6️⃣ Статистика\n"
        "7️⃣ Что бот проверяет сам\n"
        "8️⃣ Резервные копии\n"
        "9️⃣ Люди и архив"
    ),
    # 2 — admin panel
    (
        "🛡 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
        "Открывается кнопкой\n"
        "«🛡 Админ-панель» в меню.\n\n"
        "<b>Разделы:</b>\n\n"
        "• «👥 Пользователи и роли» —\n"
        "люди, их роли и имена.\n\n"
        "• «📖 Инструкция администратора»\n"
        "— эта инструкция.\n\n"
        "• «💾 Резервные копии» —\n"
        "база, откат и корзина.\n\n"
        "• «🔄 Обновить» — свежие цифры.\n\n"
        "• «✖️ Закрыть» — закрыть панель.\n\n"
        "💡 Панель видна только\n"
        "администраторам. Остальные её\n"
        "просто не увидят."
    ),
    # 3 — users and roles
    (
        "👥 <b>ПОЛЬЗОВАТЕЛИ И РОЛИ</b>\n\n"
        "В боте четыре роли:\n\n"
        "🚚 <b>Водитель</b>\n"
        "Создаёт карточки. Полностью\n"
        "работает с покраской: сдаёт,\n"
        "ищет по VIN, видит списки,\n"
        "забирает машины. Каталог\n"
        "автомобилей закрыт.\n\n"
        "👷 <b>Работник</b>\n"
        "То же, что водитель, плюс\n"
        "поиск по VIN и все карточки.\n\n"
        "🛡 <b>Администратор</b>\n"
        "Всё, что работник, плюс\n"
        "удаление карточек, статистика,\n"
        "смена ролей, переименование.\n\n"
        "👑 <b>Главный администратор</b>\n"
        "Все права, назначает\n"
        "администраторов.\n\n"
        "💡 Новый человек получает\n"
        "роль водителя."
    ),
    # 4 — changing roles
    (
        "🔄 <b>ИЗМЕНЕНИЕ РОЛИ</b>\n\n"
        "1️⃣ Откройте «🛡 Админ-панель».\n\n"
        "2️⃣ «👥 Пользователи и роли».\n\n"
        "3️⃣ Нажмите кнопку нужной роли\n"
        "рядом с человеком.\n\n"
        "<b>Ограничения:</b>\n\n"
        "• Администратор переключает\n"
        "только «Работник ↔ Водитель».\n\n"
        "• Назначить администратора\n"
        "может только главный\n"
        "администратор.\n\n"
        "• Главного администратора\n"
        "изменить нельзя.\n\n"
        "💡 После смены роли человеку\n"
        "нужно заново открыть меню."
    ),
    # 5 — renaming
    (
        "✏️ <b>ПЕРЕИМЕНОВАНИЕ</b>\n\n"
        "Имена из Телеграма часто\n"
        "непонятны. Задайте своё:\n\n"
        "1️⃣ «👥 Пользователи и роли».\n\n"
        "2️⃣ «✏️ Переименование»\n"
        "рядом с человеком.\n\n"
        "3️⃣ Отправьте новое имя.\n\n"
        "<b>Правила имени:</b>\n\n"
        "• от 2 до 64 символов;\n\n"
        "• хотя бы одна буква\n"
        "или цифра;\n\n"
        "• старое имя останется\n"
        "подсказкой в скобках.\n\n"
        "💡 Новое имя показывается\n"
        "в карточках и в покраске."
    ),
    # 6 — deletion
    (
        "🗑 <b>УДАЛЕНИЕ КАРТОЧЕК</b>\n\n"
        "Удалять могут только\n"
        "администраторы.\n\n"
        "1️⃣ Найдите карточку.\n\n"
        "2️⃣ Нажмите «🗑 Удалить».\n\n"
        "3️⃣ Подтвердите «Да, удалить».\n\n"
        "<b>Важно:</b>\n\n"
        "• карточка не исчезает бесследно,\n"
        "а скрывается из поиска;\n\n"
        "• удалить можно любую карточку,\n"
        "не только свою;\n\n"
        "• водители и работники\n"
        "удалять не могут."
    ),
    # 7 — statistics and checks
    (
        "📊 <b>СТАТИСТИКА И ПРОВЕРКИ</b>\n\n"
        "В админ-панели видны:\n\n"
        "• сколько людей и кто они\n"
        "по ролям;\n\n"
        "• сколько карточек активно,\n"
        "удалено и всего;\n\n"
        "• сколько машин на покраске\n"
        "и сколько забрали.\n\n"
        "<b>Что бот проверяет сам:</b>\n\n"
        "• размер и чёткость фото;\n\n"
        "• фото автомобиля не\n"
        "повторяется в документах;\n\n"
        "• формат VIN и поиска;\n\n"
        "• повторные автомобили;\n\n"
        "• права по роли на сервере;\n\n"
        "• имя пользователя.\n\n"
        "💡 Права проверяются на сервере:\n"
        "старые и подделанные кнопки\n"
        "ограничения не обходят."
    ),
    # 8 — backups
    (
        "💾 <b>РЕЗЕРВНЫЕ КОПИИ</b>\n\n"
        "Раздел «💾 Резервные копии»\n"
        "виден только администраторам.\n\n"
        "<b>Что внутри:</b>\n\n"
        "• «📤 Выгрузить базу» —\n"
        "бот присылает файл базы.\n\n"
        "• «📥 Загрузить базу» —\n"
        "вернуть ранее сохранённый файл.\n\n"
        "• «🕘 Откатить» — вернуть базу\n"
        "на любой прошлый день.\n\n"
        "• «♻️ Корзина» — удалённые\n"
        "карточки, их можно вернуть.\n\n"
        "• «📜 Журнал» — кто и что\n"
        "сделал с базой.\n\n"
        "• «🔥 Удалить навсегда» —\n"
        "только главный администратор\n"
        "и только через 30 дней.\n\n"
        "💡 Перед заменой бот сам\n"
        "сохраняет нынешнюю базу.\n\n"
        "💡 Фотографии сразу попадают\n"
        "в архив и не теряются."
    ),
    # 9 — people and the archive channel
    (
        "👥 <b>ЛЮДИ И АРХИВ</b>\n"
        "\n"
        "В разделе «Пользователи и роли»\n"
        "у каждого человека есть кнопки.\n"
        "\n"
        "• «✏️ Переименовать» — задать имя,\n"
        "которое видно вместо профиля.\n"
        "\n"
        "• «🗑 Удалить» — убрать человека\n"
        "из бота. Бот сначала показывает,\n"
        "сколько у него карточек, и просит\n"
        "подтвердить удаление.\n"
        "\n"
        "💡 Карточки удалённого человека\n"
        "остаются в базе и в архиве:\n"
        "история машин не пропадает.\n"
        "\n"
        "💡 Главного администратора и\n"
        "себя удалить нельзя.\n"
        "\n"
        "📡 Кнопка «Канал-архив» в разделе\n"
        "«Резервные копии» показывает,\n"
        "работает ли внешняя копия.\n"
        "\n"
        "Кнопка «Тест» отправляет в канал\n"
        "фото последней карточки: если\n"
        "фото пришло, архив работает."
    ),
)

DE_ADMIN: tuple[str, ...] = (
    # 1 — contents
    (
        "🛡 <b>Willkommen im\n"
        "Admin-Bereich!</b>\n\n"
        "Hier steht alles, was\n"
        "Administratoren und dem\n"
        "Hauptadministrator offensteht.\n\n"
        "<b>Inhalt:</b>\n\n"
        "1️⃣ Admin-Bereich\n"
        "2️⃣ Benutzer und Rollen\n"
        "3️⃣ Rolle ändern\n"
        "4️⃣ Umbenennen\n"
        "5️⃣ Karten löschen\n"
        "6️⃣ Statistik\n"
        "7️⃣ Was der Bot selbst prüft\n"
        "8️⃣ Sicherungen\n"
        "9️⃣ Personen und Archiv"
    ),
    # 2 — admin panel
    (
        "🛡 <b>ADMIN-BEREICH</b>\n\n"
        "Er öffnet sich über\n"
        "„🛡 Admin-Bereich“ im Menü.\n\n"
        "<b>Bereiche:</b>\n\n"
        "• „👥 Benutzer und Rollen“ —\n"
        "Personen, Rollen und Namen.\n\n"
        "• „📖 Anleitung für Admins“ —\n"
        "diese Anleitung.\n\n"
        "• „💾 Sicherungen“ —\n"
        "Datenbank, Rücksetzen, Papierkorb.\n\n"
        "• „🔄 Aktualisieren“ —\n"
        "aktuelle Zahlen.\n\n"
        "• „✖️ Schließen“ — Bereich\n"
        "schließen.\n\n"
        "💡 Der Bereich ist nur für\n"
        "Administratoren sichtbar.\n"
        "Alle anderen sehen ihn nicht."
    ),
    # 3 — users and roles
    (
        "👥 <b>BENUTZER UND ROLLEN</b>\n\n"
        "Es gibt vier Rollen:\n\n"
        "🚚 <b>Fahrer</b>\n"
        "Legt Karten an. Arbeitet\n"
        "vollständig mit der Lackierung:\n"
        "abgeben, per VIN suchen,\n"
        "Listen sehen, abholen. Der\n"
        "Fahrzeugkatalog bleibt verborgen.\n\n"
        "👷 <b>Mitarbeiter</b>\n"
        "Wie Fahrer, zusätzlich\n"
        "VIN-Suche und alle Karten.\n\n"
        "🛡 <b>Administrator</b>\n"
        "Wie Mitarbeiter, zusätzlich\n"
        "Karten löschen, Statistik,\n"
        "Rollen wechseln, umbenennen.\n\n"
        "👑 <b>Hauptadministrator</b>\n"
        "Alle Rechte, ernennt\n"
        "Administratoren.\n\n"
        "💡 Neue Personen starten\n"
        "als Fahrer."
    ),
    # 4 — changing roles
    (
        "🔄 <b>ROLLE ÄNDERN</b>\n\n"
        "1️⃣ „🛡 Admin-Bereich“ öffnen.\n\n"
        "2️⃣ „👥 Benutzer und Rollen“.\n\n"
        "3️⃣ Die Schaltfläche der Rolle\n"
        "neben der Person drücken.\n\n"
        "<b>Grenzen:</b>\n\n"
        "• Administratoren wechseln nur\n"
        "„Mitarbeiter ↔ Fahrer“.\n\n"
        "• Administratoren ernennt nur\n"
        "der Hauptadministrator.\n\n"
        "• Der Hauptadministrator\n"
        "kann nicht geändert werden.\n\n"
        "💡 Nach dem Wechsel muss die\n"
        "Person das Menü neu öffnen."
    ),
    # 5 — renaming
    (
        "✏️ <b>UMBENENNEN</b>\n\n"
        "Telegram-Namen sind oft\n"
        "unklar. Vergeben Sie eigene:\n\n"
        "1️⃣ „👥 Benutzer und Rollen“.\n\n"
        "2️⃣ „✏️ Umbenennen“\n"
        "neben der Person.\n\n"
        "3️⃣ Den neuen Namen senden.\n\n"
        "<b>Regeln für den Namen:</b>\n\n"
        "• 2 bis 64 Zeichen;\n\n"
        "• mindestens ein Buchstabe\n"
        "oder eine Zahl;\n\n"
        "• der alte Name bleibt als\n"
        "Hinweis in Klammern.\n\n"
        "💡 Der neue Name erscheint\n"
        "in Karten und in der Lackierung."
    ),
    # 6 — deletion
    (
        "🗑 <b>KARTEN LÖSCHEN</b>\n\n"
        "Nur Administratoren dürfen\n"
        "löschen.\n\n"
        "1️⃣ Karte finden.\n\n"
        "2️⃣ „🗑 Löschen“ drücken.\n\n"
        "3️⃣ „Ja, löschen“ bestätigen.\n\n"
        "<b>Wichtig:</b>\n\n"
        "• die Karte verschwindet nicht\n"
        "spurlos, sie wird nur aus der\n"
        "Suche genommen;\n\n"
        "• es darf jede Karte gelöscht\n"
        "werden, nicht nur die eigene;\n\n"
        "• Fahrer und Mitarbeiter\n"
        "dürfen nicht löschen."
    ),
    # 7 — statistics and checks
    (
        "📊 <b>STATISTIK UND PRÜFUNGEN</b>\n\n"
        "Im Admin-Bereich sichtbar:\n\n"
        "• wie viele Personen es gibt\n"
        "und welche Rollen sie haben;\n\n"
        "• wie viele Karten aktiv,\n"
        "gelöscht und insgesamt\n"
        "vorhanden sind;\n\n"
        "• wie viele Fahrzeuge in\n"
        "Lackierung sind und wie viele\n"
        "abgeholt wurden.\n\n"
        "<b>Was der Bot selbst prüft:</b>\n\n"
        "• Größe und Schärfe der Fotos;\n\n"
        "• drei unterschiedliche Fotos;\n\n"
        "• Format von VIN und Suche;\n\n"
        "• doppelte Fahrzeuge;\n\n"
        "• Rechte der Rolle auf dem\n"
        "Server;\n\n"
        "• den Namen des Benutzers.\n\n"
        "💡 Rechte werden auf dem Server\n"
        "geprüft: alte und gefälschte\n"
        "Schaltflächen umgehen sie nicht."
    ),
    # 8 — backups
    (
        "💾 <b>SICHERUNGEN</b>\n\n"
        "Der Bereich „💾 Sicherungen“\n"
        "ist nur für Administratoren sichtbar.\n\n"
        "<b>Inhalt:</b>\n\n"
        "• „📤 Datenbank exportieren“ —\n"
        "der Bot sendet die Datenbankdatei.\n\n"
        "• „📥 Datenbank einspielen“ —\n"
        "eine frühere Datei zurückholen.\n\n"
        "• „🕘 Zurücksetzen“ — Datenbank\n"
        "auf einen vergangenen Tag.\n\n"
        "• „♻️ Papierkorb“ — gelöschte\n"
        "Karten, sie lassen sich holen.\n\n"
        "• „📜 Protokoll“ — wer hat was\n"
        "mit der Datenbank gemacht.\n\n"
        "• „🔥 Endgültig löschen“ — nur\n"
        "der Hauptadministrator und erst\n"
        "nach 30 Tagen.\n\n"
        "💡 Vor jedem Tausch sichert\n"
        "der Bot die aktuelle Datenbank\n"
        "zuerst selbst.\n\n"
        "💡 Fotos gehen sofort ins\n"
        "Archiv und gehen nicht verloren."
    ),
    # 9 — people and the archive channel
    (
        "👥 <b>PERSONEN UND ARCHIV</b>\n"
        "\n"
        "Unter „👥 Benutzer und Rollen“\n"
        "hat jede Person Schaltflächen.\n"
        "\n"
        "• „✏️ Umbenennen“ — einen Namen\n"
        "geben, der statt des Profils\n"
        "angezeigt wird.\n"
        "\n"
        "• „🗑 Löschen“ — die Person aus\n"
        "dem Bot entfernen. Der Bot zeigt\n"
        "zuerst, wie viele Karten sie hat,\n"
        "und fragt noch einmal nach.\n"
        "\n"
        "💡 Die Karten einer gelöschten\n"
        "Person bleiben in der Datenbank\n"
        "und im Archiv: die Historie\n"
        "der Fahrzeuge bleibt erhalten.\n"
        "\n"
        "💡 Den Hauptadministrator und\n"
        "sich selbst kann niemand löschen.\n"
        "\n"
        "📡 „📡 Archivkanal“ unter „💾\n"
        "Sicherungen“ zeigt, ob die\n"
        "externe Kopie arbeitet.\n"
        "\n"
        "„🧪 Test“ sendet das Foto der\n"
        "letzten Karte in den Kanal:\n"
        "kommt es an, funktioniert\n"
        "das Archiv."
    ),
)

PAGES: dict[str, dict[str, tuple[str, ...]]] = {
    WORKER: {"ru": RU_WORKER, "de": DE_WORKER},
    ADMIN: {"ru": RU_ADMIN, "de": DE_ADMIN},
}


def page_count(which: str) -> int:
    """Number of pages in the manual, or zero for an unknown section."""

    pages = PAGES.get(which)
    if pages is None:
        return 0
    return len(pages[DEFAULT_LANGUAGE])


def is_valid_page(which: str, index: int) -> bool:
    return which in PAGES and 0 <= index < page_count(which)


def manual_text(language: str, which: str, index: int) -> str:
    """Render one page with its header and footer."""

    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    pages = PAGES[which][lang]
    safe_index = min(max(index, 0), len(pages) - 1)
    header = t(
        lang,
        "manual_header",
        title=TITLES[which][lang],
        page=safe_index + 1,
        pages=len(pages),
    )
    return f"{header}\n\n{pages[safe_index]}\n\n{t(lang, 'manual_footer')}"
