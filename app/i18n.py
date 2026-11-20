from __future__ import annotations

SUPPORTED_LANGUAGES = {"ru", "de"}
DEFAULT_LANGUAGE = "ru"

TEXTS: dict[str, dict[str, str]] = {
    "ru": {
        "choose_language": "🌐 Выберите язык интерфейса:",
        "language_saved": "✅ Язык изменён на русский.",
        "welcome": (
            "👋 <b>VIN-ПОМОЩНИК</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Бот ведёт учёт автомобилей:\n"
            "карточки, поиск по VIN и покраска.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚗 <b>АВТОМОБИЛИ</b>\n"
            "Карточка с фото, накладной и VIN,\n"
            "поиск по последним символам.\n\n"
            "🎨 <b>ПОКРАСКА</b>\n"
            "Сдать машину, посмотреть,\n"
            "что в работе, и забрать.\n\n"
            "📖 <b>ИНСТРУКЦИЯ</b>\n"
            "Правила, шаги и проверки.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "main_menu": (
            "🏠 <b>ГЛАВНОЕ МЕНЮ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите раздел кнопкой ниже \U0001f447"
        ),
        "menu_placeholder": "Выберите раздел",
        "btn_create": "➕ Создать карточку",
        "btn_search": "🔎 Найти по VIN",
        "btn_cards": "🗂 Все карточки",
        "btn_manual": "📖 Инструкция",
        "btn_settings": "🌐 Язык",
        "btn_admin": "🛡 Админ-панель",
        "btn_paint": "🎨 Покраска",
        "btn_paint_new": "📥 Сдать в покраску",
        "btn_paint_list": "📋 На покраске",
        "btn_paint_done": "✅ Забранные",
        "btn_paint_search": "🔎 Поиск по VIN",
        "btn_take_from_paint": "✅ Забрали с покраски",
        "btn_paint_menu": "🎨 В покраску",
        "btn_home": "🏠 В меню",
        "btn_back": "⬅️ Назад",
        "btn_forward": "Вперёд ➡️",
        "btn_manual_admin": "📖 Инструкция администратора",
        "manual_header": (
            "📖 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n<b>Страница {page} из {pages}</b>"
        ),
        "manual_footer": (
            "━━━━━━━━━━━━━━━━━━\n"
            "⬅️ ➡️ — листать страницы.\n"
            "«✖️ Закрыть» — закрыть инструкцию."
        ),
        "manual_admin_only": (
            "⛔ Инструкция администратора доступна только администраторам."
        ),
        "btn_paint_vin_photo": "🔢 Фото VIN",
        "btn_yes_take": "✅ Да, забрали",
        "btn_cancel": "❌ Отмена",
        "btn_confirm": "✅ Всё верно",
        "btn_fix_char": "🔧 Исправить один знак",
        "btn_edit": "✏️ Исправить VIN",
        "btn_retake": "📷 Переснять VIN",
        "btn_invoice": "📄 Накладная",
        "btn_vehicle_photo": "🚗 Фото автомобиля",
        "btn_delete": "🗑 Удалить",
        "btn_close": "✖️ Закрыть",
        "btn_yes_delete": "🗑 Да, удалить",
        "btn_no": "↩️ Нет",
        "btn_prev": "⬅️",
        "btn_next": "➡️",
        "btn_admin_users": "👥 Пользователи и роли",
        "btn_admin_refresh": "🔄 Обновить",
        "btn_admin_back": "⬅️ В админ-панель",
        "btn_set_admin": "🛡 Админ",
        "btn_set_worker": "👷 Работник",
        "btn_set_driver": "🚚 Водитель",
        "btn_rename": "✏️ Переименовать",
        "btn_delete_user": "🗑 Удалить",
        "admin_user_unnamed": "Без имени",
        "btn_archive_channel": "📡 Канал-архив",
        "archive_title": "📡 <b>КАНАЛ-АРХИВ</b>",
        "archive_state_line": "Состояние: <b>{state}</b>",
        "archive_state_on": "включён",
        "archive_state_off": "отключён",
        "archive_channel_line": "Канал: <code>{channel}</code>",
        "archive_immediate_line": "Мгновенная копия каждой карточки: <b>{value}</b>",
        "archive_digest_line": "Выгрузка базы каждый день в <b>{time}</b>",
        "archive_yes": "да",
        "archive_no": "нет",
        "archive_test_ok": "✅ Тест прошёл: сообщение ушло в канал.",
        "archive_test_photo_ok": (
            "✅ Тест прошёл: фото карточки №{card_id} ушло в канал."
        ),
        "archive_test_fail": "❌ Тест не прошёл:\n{error}",
        "archive_digest_ok": "✅ Сводка и копия базы отправлены в канал.",
        "archive_digest_fail": "❌ Выгрузка не удалась:\n{error}",
        "btn_archive_test": "🧪 Тест",
        "btn_archive_digest": "📦 Выгрузить сейчас",
        "btn_archive_retry": "📤 Отправить пропущенное",
        "archive_retry_done": "✅ В канал догружено карточек: {count}.",
        "archive_retry_none": "✅ Всё отправлено: пропущенных карточек нет.",
        "archive_hint": (
            "\n\nКаждая новая карточка уходит в канал сразу: фото автомобиля, "
            "накладная и фото VIN, в подписи — полный VIN. Раз в сутки бот "
            "отправляет туда же сводку и файл базы."
        ),
        "btn_second_reader": "🔎 Второй читатель",
        "second_reader_title": "🔎 <b>ВТОРОЙ ЧИТАТЕЛЕЦ</b>",
        "second_reader_state_line": "Состояние: <b>{state}</b>",
        "second_reader_state_on": "подключён",
        "second_reader_state_off": "не нужен, бот читает сам",
        "second_reader_key_line": "Ключ: <code>{value}</code>",
        "second_reader_key_absent": "не указан",
        "second_reader_key_shown": "…{tail} ({length} знаков)",
        "second_reader_mode_line": "Режим: <b>{mode}</b>",
        "second_reader_mode_off": "off — никогда не спрашивать",
        "second_reader_mode_auto": "auto — только по трудным снимкам",
        "second_reader_mode_always": "always — по каждому снимку",
        "second_reader_mode_first": "first — облако читает первым, бот — запасной",
        "second_reader_model_line": "Модель: <code>{model}</code>",
        "second_reader_hint": (
            "\n\nБот всегда читает VIN сам: без интернета и без оплаты. "
            "Второй читатель подключается только к тем снимкам, которые бот "
            "прочитал неуверенно, и его ответ проверяется по контрольной сумме "
            "VIN. Ключ добавляется в файл .env рядом с токеном бота."
        ),
        "second_reader_test_ok": "✅ Ключ принят: {model} ответил за {seconds:.1f} с.",
        "second_reader_test_fail": (
            "❌ Второй читатель не ответил:\n{error}\n\n"
            "Бот от этого не сломался: он читает снимки сам."
        ),
        "btn_second_reader_test": "🧪 Проверить ключ",
        "ocr_second_opinion_took": (
            "🔎 Второй читатель разобрал код: <code>{vin}</code>\n"
            "Сверьте с табличкой на автомобиле."
        ),
        "ocr_second_opinion_differs": (
            "🔎 Второй читатель видит <code>{vin}</code>, бот прочитал "
            "<code>{local}</code>. Оставлен вариант бота — сверьте с табличкой."
        ),
        "ocr_second_opinion_agrees": (
            "🔎 Второй читатель подтвердил код: <code>{vin}</code>"
        ),
        "ocr_cloud_read": "🔎 Код прочитан вторым читателем — сверьте с табличкой.",
        "ocr_second_opinion_partial": (
            "🔎 Второй читатель разобрал не всё: <code>{partial}</code>\n"
            "Знак ? стоит там, где он символ прочитать не смог."
        ),
        "admin_delete_confirm": (
            "🗑 <b>УДАЛИТЬ ПОЛЬЗОВАТЕЛЯ?</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "<b>{name}</b> · ID: <code>{user_id}</code>\n"
            "Роль: <b>{role}</b>\n\n"
            "🚗 Карточек автомобилей: <b>{cards}</b>\n"
            "🎨 Карточек покраски: <b>{paint}</b>\n\n"
            "⚠️ Пользователь будет удалён из бота. Его карточки остаются в базе "
            "и в канале-архиве. Если он снова напишет /start, то появится "
            "заново с ролью «Водитель»."
        ),
        "admin_delete_done": (
            "✅ Пользователь <b>{user}</b> удалён. Его карточки ({cards}) сохранены."
        ),
        "admin_delete_forbidden": "⛔ Этого пользователя удалять нельзя.",
        "admin_delete_self": "⛔ Нельзя удалить самого себя.",
        "admin_delete_missing": "⚠️ Этого пользователя уже нет в базе.",
        "access_denied_short": "Доступ запрещён.",
        "access_denied": (
            "⛔ Доступ к рабочему боту не выдан. Передайте администратору ваш "
            "Telegram ID: <code>{user_id}</code>"
        ),
        "role_driver": "Водитель",
        "role_worker": "Работник",
        "role_admin": "Администратор",
        "role_superadmin": "Главный администратор",
        "welcome_role": "Ваша роль: <b>{role}</b>.",
        "role_forbidden": "⛔ Ваша роль не разрешает это действие.",
        "admin_forbidden": "⛔ Этот раздел доступен только администраторам.",
        "admin_panel": (
            "🛡 <b>АДМИН-ПАНЕЛЬ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Ваша роль: <b>{role}</b>\n\n"
            "👥 <b>ЛЮДИ</b>\n"
            "Всего: <b>{users}</b>\n"
            "🛡 Администраторов: <b>{all_admins}</b>\n"
            "👑 из них главных: <b>{main_admins}</b>\n"
            "🛡 обычных: <b>{admins}</b>\n"
            "👷 Работников: <b>{workers}</b>\n"
            "🚚 Водителей: <b>{drivers}</b>\n\n"
            "🚗 <b>КАРТОЧКИ</b>\n"
            "Активных: <b>{active_cards}</b>\n"
            "🗑 Удалённых: <b>{deleted_cards}</b>\n"
            "📦 Всего: <b>{total_cards}</b>\n\n"
            "🎨 <b>ПОКРАСКА</b>\n"
            "На покраске: <b>{paint_in_progress}</b>\n"
            "✅ Забрали: <b>{paint_completed}</b>\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "admin_users": (
            "👥 <b>ПОЛЬЗОВАТЕЛИ И РОЛИ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Страница {page} из {pages} · всего {total}\n\n{users}"
        ),
        "admin_users_empty": "Пользователи ещё не зарегистрированы.",
        "admin_manage_hint": (
            "\n\nГлавный администратор назначает любую роль. Администратор может "
            "переключать только роли «Работник» и «Водитель». Оба могут "
            "переименовывать любого пользователя списка. Кнопка \U0001f5d1 "
            "удаляет водителя или работника, главный администратор удаляет "
            "любого, кроме себя."
        ),
        "admin_view_hint": (
            "\n\nВы не можете изменять роль главного или другого администратора."
        ),
        "admin_role_changed": (
            "✅ Пользователю <b>{user}</b> назначена роль «{role}»."
        ),
        "admin_user_telegram_note": " (Telegram: {name})",
        "admin_rename_prompt": (
            "✏️ Введите новое имя для <b>{user}</b>.\n"
            "Сейчас отображается: <b>{name}</b>.\n"
            "От 2 до 64 символов, минимум одна буква или цифра."
        ),
        "admin_rename_done": "✅ Пользователю <b>{user}</b> задано имя «{name}».",
        "admin_rename_invalid": (
            "❌ Имя должно содержать от 2 до 64 символов и хотя бы одну букву "
            "или цифру."
        ),
        "admin_rename_forbidden": "⛔ Вы не можете переименовать этого пользователя.",
        "admin_role_forbidden": "⛔ Вы не можете назначить эту роль пользователю.",
        "admin_master_protected": "Главного администратора нельзя изменить из бота.",
        "admin_user_missing": "Пользователь не найден. Сначала он должен открыть бота.",
        "admin_role_changed_hint": "Новая роль появится в меню пользователя после /menu.",
        "create_vehicle_photo": (
            "🚗 <b>ШАГ 1 ИЗ 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●○○]\n\n"
            "Отправьте одну чёткую фотографию автомобиля."
        ),
        "vehicle_photo_required": "Нужно отправить фотографию автомобиля именно как фото.",
        "photo_too_small": (
            "❌ Фотография слишком маленькая. Отправьте более чёткое фото размером "
            "не менее 320×240 пикселей."
        ),
        "photo_too_large": "❌ Фотография слишком большая. Максимальный размер — 10 МБ.",
        "vin_photo_too_small": (
            "❌ VIN-фрагмент слишком маленький. Нужен чёткий кадр не менее "
            "160×50 пикселей, где видна вся строка VIN."
        ),
        "photo_reused": (
            "❌ Это фото автомобиля — оно уже использовано на первом шаге. "
            "Для VIN нужна фотография документа: накладная или её фрагмент."
        ),
        "create_invoice_photo": (
            "📄 <b>ШАГ 2 ИЗ 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●○]\n\n"
            "Отправьте фотографию <b>полной накладной</b>. "
            "Она будет сохранена и доступна внутри карточки автомобиля."
        ),
        "invoice_photo_required": "Нужно отправить фотографию полной накладной.",
        "create_vin_photo": (
            "🔢 <b>ШАГ 3 ИЗ 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●●]\n\n"
            "Отправьте фотографию, на которой виден VIN.\n\n"
            "Подойдёт <b>обрезанный крупный фрагмент</b> — так читается "
            "надёжнее всего. Подойдёт и <b>накладная целиком</b>: можно "
            "прислать её ещё раз или нажать кнопку ниже — бот найдёт код сам."
        ),
        "btn_use_invoice": "📄 Взять VIN из накладной",
        "vin_photo_required": "Нужно отправить фотографию с VIN.",
        "ocr_processing": "🔍 Распознаю VIN на фотографии…",
        "ocr_found": (
            "Распознан VIN — код можно скопировать одним касанием:\n\n"
            "<pre>{vin_display}</pre>\n"
            "Последние 6 символов: <b>{suffix}</b>\n\n"
            "Сверьте все 17 символов с фотографией. "
            "Один знак не совпал — нажмите «Исправить один знак»."
        ),
        "ocr_not_found": (
            "⚠️ Не удалось уверенно прочитать полный VIN.\n"
            "Если код на фото есть, но не читается — снимите его "
            "крупным планом: без бликов, в фокусе, чтобы VIN занимал "
            "половину кадра.\n"
            "Сейчас введите вручную <b>весь VIN (17 символов)</b> или его "
            "<b>последние 6 символов</b>."
        ),
        "ocr_partial": (
            "🔎 VIN прочитан не полностью: знаки <b>{positions}</b> разобрать "
            "не удалось. Остальное прочитано — заполните только их.\n\n"
            "<pre>{vin}</pre>\n\n"
            "Знак «?» — это место, где камера не смогла разобрать символ. "
            "Я его не угадываю: сверьте с табличкой и нажмите на номер знака."
        ),
        "ocr_retake": ("📷 <b>Снимок стоит переделать.</b> {instructions}"),
        "vin_has_gaps": (
            "В коде есть незаполненные знаки. Заполните их или введите VIN целиком."
        ),
        "ocr_weak": (
            "⚠️ Фотография нечёткая, VIN прочитан неуверенно. "
            "Проверьте каждый символ — сверьте с табличкой. "
            "Не совпало — нажмите «Исправить»."
        ),
        "ocr_check_digit": (
            "⚠️ VIN прочитан, но контрольная цифра не сошлась: "
            "минимум один символ распознан неверно. "
            "Сверьте каждый символ с табличкой, особенно девятый. "
            "Не совпало — нажмите «Исправить»."
        ),
        "ocr_no_text": (
            "\U0001f4f7 \u0422\u0435\u043a\u0441\u0442 \u043d\u0430 \u0444\u043e\u0442\u043e \u043d\u0435 \u0447\u0438\u0442\u0430\u0435\u0442\u0441\u044f. "
            "\u0421\u043d\u0438\u043c\u0438\u0442\u0435 VIN \u043a\u0440\u0443\u043f\u043d\u044b\u043c "
            "\u043f\u043b\u0430\u043d\u043e\u043c: \u0442\u0430\u0431\u043b\u0438\u0447\u043a\u0430 "
            "\u043f\u043e\u0434 \u043b\u043e\u0431\u043e\u0432\u044b\u043c \u0441\u0442\u0435\u043a\u043b\u043e\u043c "
            "\u0438\u043b\u0438 \u043d\u0430\u043a\u043b\u0435\u0439\u043a\u0430 \u0432 "
            "\u043f\u0440\u043e\u0451\u043c\u0435 \u0434\u0432\u0435\u0440\u0438, \u0431\u0435\u0437 "
            "\u0431\u043b\u0438\u043a\u043e\u0432, \u0447\u0442\u043e\u0431\u044b \u043a\u043e\u0434 "
            "\u0437\u0430\u043d\u0438\u043c\u0430\u043b \u0432\u0435\u0441\u044c \u043a\u0430\u0434\u0440. "
            "\u0421\u0435\u0439\u0447\u0430\u0441 \u0432\u0432\u0435\u0434\u0438\u0442\u0435 "
            "<b>\u0432\u0435\u0441\u044c VIN (17 \u0441\u0438\u043c\u0432\u043e\u043b\u043e\u0432)</b> "
            "\u0438\u043b\u0438 <b>\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 6</b>."
        ),
        "ocr_unavailable": (
            "⚠️ Модуль распознавания сейчас недоступен. Введите весь VIN "
            "(17 символов) или последние 6 символов вручную."
        ),
        "ocr_fix_which": (
            "Какой знак исправить? Нажмите на него.\n\n"
            "Знак, помеченный «?», машина прочитала двояко — с него и начните."
        ),
        "ocr_fix_replace": (
            "Знак {position}: сейчас «{current}». Чем заменить?\n\n"
            "Подходящие знаки — с ними контрольная цифра сходится — отмечены точкой."
        ),
        "ocr_fix_hint": (
            "Похоже, знак {position} прочитан как «{current}», "
            "а должен быть «{fixed}»: контрольная цифра сходится только так."
        ),
        "ocr_fix_done": (
            "Знак {position} заменён на «{char}».\n\n"
            "<pre>{vin}</pre>\n\n"
            "Сверьте остальные знаки с табличкой."
        ),
        "manual_vin_prompt": (
            "Введите весь VIN (17 символов) или последние 6 символов. "
            "Допустимы латинские буквы и цифры.\n\n"
            "Можно скопировать код из сообщения выше и исправить в нём "
            "один знак — так быстрее, чем набирать заново."
        ),
        "vin_invalid": (
            "❌ Неверный формат. Нужны ровно <b>17</b> или <b>6</b> латинских "
            "букв/цифр. В VIN не используются I, O и Q. Лишний текст не допускается."
        ),
        "text_too_long": "❌ Значение слишком длинное. Проверьте ввод и отправьте снова.",
        "duplicate": (
            "⚠️ Автомобиль с этим полным VIN уже существует: карточка #{card_id}. "
            "Новая карточка не создана."
        ),
        "card_saved": (
            "✅ <b>КАРТОЧКА СОЗДАНА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Номер карточки: <b>#{card_id}</b>\n\n"
            "Она уже находится в поиске по VIN."
        ),
        "search_prompt": (
            "🔎 <b>ПОИСК ПО VIN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Введите последние <b>4 или 6</b> символов VIN\n"
            "или весь VIN целиком.\n\n"
            "Также можно отправить фото полного VIN — бот распознает его и выполнит поиск."
        ),
        "search_invalid": (
            "❌ Введите 4, 6 или 17 знаков: последние символы VIN "
            "или VIN целиком. Либо отправьте фото VIN."
        ),
        "search_photo_failed": (
            "Не удалось прочитать полный VIN на фото. Попробуйте другое фото или "
            "введите последние 4/6 символов вручную."
        ),
        "no_results": (
            "🔍 <b>НИЧЕГО НЕ НАЙДЕНО</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "По окончанию VIN <b>{query}</b> карточек нет."
        ),
        "all_empty": (
            "📂 <b>КАРТОЧЕК ПОКА НЕТ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Создайте первую карточку кнопкой «➕ Создать карточку»."
        ),
        "cancelled": (
            "↩️ <b>ДЕЙСТВИЕ ОТМЕНЕНО</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Можно начать заново в любой момент."
        ),
        "settings": (
            "🌐 <b>ЯЗЫК И НАСТРОЙКИ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Ваша роль: <b>{role}</b>\n\n"
            "Выберите язык интерфейса:"
        ),
        "help": (
            "❓ <b>БЫСТРАЯ ПОМОЩЬ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ «➕ Создать карточку»\n"
            "Три фото: автомобиль, накладная,\n"
            "отдельный фрагмент VIN.\n\n"
            "2️⃣ «🔎 Найти по VIN»\n"
            "Последние 4 или 6 символов\n"
            "либо фото VIN.\n\n"
            "3️⃣ «🎨 Покраска»\n"
            "Сдать машину, посмотреть,\n"
            "что в работе, и забрать.\n\n"
            "4️⃣ «📖 Инструкция»\n"
            "Полные правила по шагам,\n"
            "включая проверки.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Команды:\n"
            "/menu — меню, /manual — инструкция,\n"
            "/cancel — отмена, /help — помощь."
        ),
        "unknown": "Используйте кнопки главного меню.",
        "card_title": "🚗 <b>Карточка #{card_id}</b>",
        "card_vin": "🔢 VIN: <code>{masked_vin}</code>",
        "card_search_keys": "🔎 Поиск: <b>{suffix6}</b> или <b>{suffix4}</b>",
        "card_owner": "👤 Добавил: {owner}",
        "card_date": "📅 Дата: {date}",
        "card_position": "📄 Результат: {position} из {total}",
        "card_invoice_view": "📄 <b>Накладная к карточке #{card_id}</b>",
        "delete_question": "Удалить карточку #{card_id}? Это действие скроет её из поиска.",
        "deleted": (
            "🗑 <b>КАРТОЧКА УДАЛЕНА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Номер карточки: <b>#{card_id}</b>\n\n"
            "В поиске она больше не появляется."
        ),
        "delete_forbidden": "Удалять карточки могут только администраторы.",
        "already_deleted": "Карточка уже удалена или не существует.",
        "stale_button": ("Это меню устарело. Откройте его заново."),
        "operation_expired": "Действие устарело. Начните заново из главного меню.",
        "paint_menu": (
            "🎨 <b>ПОКРАСКА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📥 <b>Сдать в покраску</b>\n"
            "Два фото: автомобиль и VIN.\n\n"
            "📋 <b>На покраске</b>\n"
            "Машины, которые сейчас красят,\n"
            "с кнопкой «Забрали с покраски».\n\n"
            "✅ <b>Забранные</b>\n"
            "Машины, которые уже забрали.\n\n"
            "🔎 <b>Поиск по VIN</b>\n"
            "Найти машину и отметить выдачу.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "paint_create_vehicle_photo": (
            "🎨 <b>ШАГ 1 ИЗ 2</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●○]\n\n"
            "Отправьте фотографию автомобиля, который отдают на покраску."
        ),
        "paint_vehicle_photo_required": (
            "Нужно отправить именно фотографию автомобиля, а не текст."
        ),
        "paint_create_vin_photo": (
            "🔢 <b>ШАГ 2 ИЗ 2</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●]\n\n"
            "Отправьте <b>обрезанный крупный фрагмент VIN</b> этого автомобиля.\n\n"
            "В кадре должны быть надпись «Fahrgestell-Nummer» или "
            "«Fahrzeug-Identifizierungsnummer» и вся строка VIN из 17 символов. "
            "Не обрезайте первый и последний символ."
        ),
        "paint_vin_photo_required": "Нужно отправить обрезанную фотографию VIN.",
        "paint_search_prompt": (
            "🔎 <b>ПОИСК ПО VIN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Введите последние <b>4 или 6</b> символов VIN\n"
            "или весь VIN целиком.\n\n"
            "Ищутся автомобили раздела «Покраска»: и те, что сейчас на покраске, "
            "и уже забраные. Также можно отправить фото VIN — бот распознает его."
        ),
        "paint_saved": (
            "✅ <b>МАШИНА В ПОКРАСКЕ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Номер карточки: <b>#{card_id}</b>\n\n"
            "Она видна в разделе «📋 На покраске»."
        ),
        "paint_duplicate": (
            "⚠️ Этот автомобиль уже числится на покраске: карточка #{card_id}. "
            "Повторная запись не создана."
        ),
        "paint_empty": "📋 Сейчас машин на покраске нет.",
        "paint_done_empty": "✅ Список забраных машин пока пуст.",
        "paint_no_results": (
            "В покраске ничего не найдено по окончанию VIN <b>{query}</b>."
        ),
        "paint_card_title": "🎨 <b>Покраска #{card_id}</b>",
        "paint_status_in": "Статус: <b>на покраске</b>",
        "paint_status_done": "Статус: <b>покрашен, забрали</b>",
        "paint_card_sent": "Отдал в покраску: {owner}",
        "paint_card_taken": "Забрал с покраски: {owner}",
        "paint_card_taken_date": "Дата выдачи: {date}",
        "paint_card_vin_view": "🔢 <b>VIN к карточке покраски #{card_id}</b>",
        "paint_take_question": (
            "Автомобиль забрали с покраски?\n"
            "Карточка #{card_id} исчезнет из раздела «На покраске» и появится "
            "в разделе «Покрашены · забрали»."
        ),
        "paint_taken": "✅ Карточка #{card_id} перенесена в «Покрашены · забрали».",
        "paint_already_taken": "Этот автомобиль уже забрали с покраски.",
        "btn_admin_backup": "💾 Резервные копии",
        "backup_title": (
            "💾 <b>РЕЗЕРВНЫЕ КОПИИ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🗂 Копий на сервере: <b>{snapshots}</b>\n"
            "🕓 Последняя: <b>{last}</b>\n"
            "📦 Размер базы: <b>{size}</b>\n"
            "♻️ В корзине: <b>{trash}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Выгрузите базу, загрузите её обратно\n"
            "или откатитесь на нужный день.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_last_never": "ещё не создавалась",
        "btn_backup_export": "📤 Выгрузить базу",
        "btn_backup_import": "📥 Загрузить базу",
        "btn_backup_rollback": "🕘 Откатить",
        "btn_backup_trash": "♻️ Корзина",
        "btn_backup_journal": "📜 Журнал",
        "backup_export_caption": (
            "💾 <b>БАЗА ДАННЫХ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📅 {date}\n"
            "📦 Размер: {size}\n\n"
            "Этот файл можно загрузить обратно\n"
            "через «📥 Загрузить базу»."
        ),
        "backup_export_failed": (
            "❌ Не удалось подготовить файл базы.\nПопробуйте ещё раз позже."
        ),
        "backup_import_prompt": (
            "📥 <b>ЗАГРУЗКА БАЗЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Пришлите файл базы, который вы\n"
            "выгружали раньше (.db или .db.gz).\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Перед заменой бот сам сохранит\n"
            "нынешнюю базу как отдельную копию.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_received": (
            "📥 <b>ПРОВЕРКА ФАЙЛА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "В файле:\n"
            "🗂 Карточек: <b>{cards}</b>\n"
            "👥 Пользователей: <b>{users}</b>\n"
            "📦 Размер: {size}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Заменить нынешнюю базу этой?\n"
            "У вас сейчас: {current_cards} карточек.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_bad": (
            "❌ <b>ФАЙЛ НЕ ПОДОШЁЛ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{reason}\n\n"
            "Пришлите другой файл или нажмите\n"
            "«{cancel}»."
        ),
        "backup_import_done": (
            "✅ <b>БАЗА ЗАГРУЖЕНА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🗂 Карточек: <b>{cards}</b>\n"
            "👥 Пользователей: <b>{users}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Предыдущая база сохранена:\n"
            "🗂 {snapshot}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_failed": (
            "❌ Не удалось загрузить базу.\nНынешняя база не изменена."
        ),
        "btn_backup_apply": "✅ Да, заменить",
        "backup_list_title": (
            "🕘 <b>ОТКАТ БАЗЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Выберите день, на который нужно\n"
            "вернуть базу.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Страница {page} из {pages}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_list_empty": (
            "🕘 <b>ОТКАТ БАЗЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Копий пока нет. Бот создаёт их\n"
            "сам каждый день."
        ),
        "backup_page_label": "Страница {page} из {pages}",
        "backup_confirm": (
            "🕘 <b>ПОДТВЕРДИТЕ ОТКАТ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Вернуть базу на {label}?\n\n"
            "Всё, что добавлено после этой\n"
            "копии, будет потеряно.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "btn_yes_rollback": "🕘 Да, откатить",
        "backup_restored": (
            "✅ <b>ОТКАТ ВЫПОЛНЕН</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Вернулись на: {label}\n\n"
            "🗂 Карточек: <b>{cards}</b>\n"
            "👥 Пользователей: <b>{users}</b>\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_title": (
            "♻️ <b>КОРЗИНА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Удалённых карточек: <b>{total}</b>\n\n"
            "Карточку можно вернуть.\n"
            "Уничтожить навсегда можно\n"
            "только через {days} дней.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "{page_label}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_empty": (
            "♻️ <b>КОРЗИНА ПУСТА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Удалённые карточки появляются здесь\n"
            "и хранятся {days} дней."
        ),
        "trash_card": (
            "♻️ <b>УДАЛЁННАЯ КАРТОЧКА #{card_id}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔑 VIN: <code>{vin}</code>\n"
            "👤 Добавил: {owner}\n"
            "🗑 Удалил: {deleter}\n"
            "🕓 Когда: {date}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_deleter_unknown": "неизвестно",
        "btn_restore": "♻️ Восстановить",
        "btn_purge": "🔥 Удалить навсегда",
        "trash_restored": "✅ Карточка №{card_id} восстановлена.",
        "trash_purged": "🔥 Карточка №{card_id} удалена навсегда.",
        "trash_purge_too_early": (
            "⏳ Уничтожить карточку можно только\nчерез {days} дней после удаления."
        ),
        "trash_purge_forbidden": (
            "⛔ Уничтожать карточки навсегда может\nтолько главный администратор."
        ),
        "trash_already": "Эта карточка уже восстановлена.",
        "trash_list_title": (
            "♥️ <b>КОРЗИНА</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{headline}\n"
            "{filter}"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{lines}\n\n"
            "Страница {page} из {pages}. Нажмите на\n"
            "карточку, чтобы открыть её."
        ),
        "trash_list_total": "Удалённых карточек: <b>{total}</b>",
        "trash_list_found": "Найдено: <b>{total}</b>",
        "trash_list_line": "{index}. №{card_id} · <code>{vin}</code> · {date} · {owner}",
        "trash_list_button": "№{card_id} · {vin} · {date} · {owner}",
        "btn_trash_find": "🔍 Найти",
        "btn_trash_clear": "❌ Сбросить поиск",
        "btn_trash_back_list": "⬅️ К списку",
        "trash_find_prompt": (
            "🔍 <b>ПОИСК В КОРЗИНЕ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Введите последние 4–6 знаков VIN,\n"
            "VIN целиком или часть имени того,\n"
            "кто добавил карточку."
        ),
        "trash_find_invalid": (
            "Так искать не могу. Нужно от 3 до 64 знаков: VIN или имя."
        ),
        "trash_filter_active": "Фильтр: <b>{query}</b>",
        "trash_nothing_found": ("В корзине ничего нет по запросу «{query}»."),
        "trash_search_cleared": "Поиск сброшен.",
        "journal_title": (
            "📜 <b>ЖУРНАЛ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Кто и что делал с базой.\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{entries}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "journal_empty": "Записей пока нет.",
        "journal_entry": "{icon} {action}\n👤 {actor} · 🕓 {date}",
        "audit_card_created": "Создана карточка",
        "audit_card_deleted": "Удалена карточка",
        "audit_card_restored": "Восстановлена карточка",
        "audit_card_purged": "Уничтожена карточка",
        "audit_backup_created": "Создана копия",
        "audit_backup_exported": "Выгружена база",
        "audit_backup_uploaded": "Загружена база",
        "audit_backup_restored": "Откат базы",
        "audit_role_changed": "Смена роли",
        "audit_user_renamed": "Переименование",
        "audit_unknown": "Действие",
        "backup_no_sqlite": ("❌ Резервные копии доступны только\nдля базы SQLite."),
        "backup_forbidden": "⛔ Раздел доступен только администраторам.",
        "backup_import_need_file": "Нужен именно файл базы (.db или .db.gz).",
        "backup_import_error": "Не удалось прочитать файл.",
        "operation_cancelled": "↩️ Отменено.",
    },
    "de": {
        "choose_language": "🌐 Sprache der Benutzeroberfläche wählen:",
        "language_saved": "✅ Sprache wurde auf Deutsch geändert.",
        "welcome": (
            "👋 <b>VIN-ASSISTENT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Der Bot erfasst Fahrzeuge:\n"
            "Karten, VIN-Suche und Lackierung.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🚗 <b>FAHRZEUGE</b>\n"
            "Karte mit Foto, Beleg und VIN,\n"
            "Suche nach den Endzeichen.\n\n"
            "🎨 <b>LACKIERUNG</b>\n"
            "Fahrzeug abgeben, ansehen,\n"
            "was läuft, und abholen.\n\n"
            "📖 <b>ANLEITUNG</b>\n"
            "Regeln, Schritte und Prüfungen.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "main_menu": (
            "🏠 <b>HAUPTMENÜ</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Bitte einen Bereich unten wählen \U0001f447"
        ),
        "menu_placeholder": "Bereich wählen",
        "btn_create": "➕ Fahrzeug anlegen",
        "btn_search": "🔎 Nach VIN suchen",
        "btn_cards": "🗂 Alle Karten",
        "btn_manual": "📖 Anleitung",
        "btn_settings": "🌐 Sprache",
        "btn_admin": "🛡 Admin-Bereich",
        "btn_paint": "🎨 Lackierung",
        "btn_paint_new": "📥 In Lackierung geben",
        "btn_paint_list": "📋 In Lackierung",
        "btn_paint_done": "✅ Abgeholt",
        "btn_paint_search": "🔎 Nach VIN suchen",
        "btn_take_from_paint": "✅ Aus Lackierung abgeholt",
        "btn_paint_menu": "🎨 Zur Lackierung",
        "btn_home": "🏠 Zum Menü",
        "btn_back": "⬅️ Zurück",
        "btn_forward": "Weiter ➡️",
        "btn_manual_admin": "📖 Anleitung für Admins",
        "manual_header": (
            "📖 <b>{title}</b>\n━━━━━━━━━━━━━━━━━━\n<b>Seite {page} von {pages}</b>"
        ),
        "manual_footer": (
            "━━━━━━━━━━━━━━━━━━\n"
            "⬅️ ➡️ — Seiten blättern.\n"
            "„✖️ Schließen“ — Anleitung schließen."
        ),
        "manual_admin_only": (
            "⛔ Die Anleitung für Admins ist nur für Administratoren."
        ),
        "btn_paint_vin_photo": "🔢 VIN-Foto",
        "btn_yes_take": "✅ Ja, abgeholt",
        "btn_cancel": "❌ Abbrechen",
        "btn_confirm": "✅ Angaben stimmen",
        "btn_fix_char": "🔧 Ein Zeichen korrigieren",
        "btn_edit": "✏️ VIN korrigieren",
        "btn_retake": "📷 VIN neu fotografieren",
        "btn_invoice": "📄 Beleg",
        "btn_vehicle_photo": "🚗 Fahrzeugfoto",
        "btn_delete": "🗑 Löschen",
        "btn_close": "✖️ Schließen",
        "btn_yes_delete": "🗑 Ja, löschen",
        "btn_no": "↩️ Nein",
        "btn_prev": "⬅️",
        "btn_next": "➡️",
        "btn_admin_users": "👥 Benutzer und Rollen",
        "btn_admin_refresh": "🔄 Aktualisieren",
        "btn_admin_back": "⬅️ Zum Admin-Bereich",
        "btn_set_admin": "🛡 Admin",
        "btn_set_worker": "👷 Mitarbeiter",
        "btn_set_driver": "🚚 Fahrer",
        "btn_rename": "✏️ Umbenennen",
        "btn_delete_user": "🗑 Löschen",
        "admin_user_unnamed": "Ohne Namen",
        "btn_archive_channel": "📡 Archivkanal",
        "archive_title": "📡 <b>ARCHIVKANAL</b>",
        "archive_state_line": "Status: <b>{state}</b>",
        "archive_state_on": "aktiv",
        "archive_state_off": "aus",
        "archive_channel_line": "Kanal: <code>{channel}</code>",
        "archive_immediate_line": "Sofortkopie jeder Karte: <b>{value}</b>",
        "archive_digest_line": "Datenbank-Export täglich um <b>{time}</b>",
        "archive_yes": "ja",
        "archive_no": "nein",
        "archive_test_ok": "✅ Test bestanden: Nachricht im Kanal angekommen.",
        "archive_test_photo_ok": (
            "✅ Test bestanden: Foto der Karte Nr.{card_id} im Kanal angekommen."
        ),
        "archive_test_fail": "❌ Test fehlgeschlagen:\n{error}",
        "archive_digest_ok": (
            "✅ Tagesübersicht und Datenbankkopie wurden in den Kanal gesendet."
        ),
        "archive_digest_fail": "❌ Export fehlgeschlagen:\n{error}",
        "btn_archive_test": "🧪 Test",
        "btn_archive_digest": "📦 Jetzt exportieren",
        "btn_archive_retry": "📤 Fehlendes senden",
        "archive_retry_done": "✅ Karten in den Kanal nachgesendet: {count}.",
        "archive_retry_none": "✅ Alles gesendet: es fehlen keine Karten.",
        "archive_hint": (
            "\n\nJede neue Karte geht sofort in den Kanal: Foto des Fahrzeugs, "
            "Lieferschein und VIN-Foto, in der Bildunterschrift die vollständige "
            "FIN. Einmal täglich sendet der Bot dorthin die Übersicht und die "
            "Datenbankdatei."
        ),
        "btn_second_reader": "🔎 Zweitleser",
        "second_reader_title": "🔎 <b>ZWEITLESER</b>",
        "second_reader_state_line": "Status: <b>{state}</b>",
        "second_reader_state_on": "verbunden",
        "second_reader_state_off": "nicht nötig, der Bot liest selbst",
        "second_reader_key_line": "Schlüssel: <code>{value}</code>",
        "second_reader_key_absent": "nicht angegeben",
        "second_reader_key_shown": "…{tail} ({length} Zeichen)",
        "second_reader_mode_line": "Modus: <b>{mode}</b>",
        "second_reader_mode_off": "off — nie fragen",
        "second_reader_mode_auto": "auto — nur bei schwierigen Fotos",
        "second_reader_mode_always": "always — bei jedem Foto",
        "second_reader_mode_first": (
            "first — Cloud liest zuerst, der Bot ist der Rückweg"
        ),
        "second_reader_model_line": "Modell: <code>{model}</code>",
        "second_reader_hint": (
            "\n\nDer Bot liest die FIN immer selbst: ohne Internet und ohne "
            "Kosten. Der Zweitleser wird nur bei Fotos gefragt, die der Bot "
            "unsicher gelesen hat, und seine Antwort wird über die "
            "Prüfziffer der FIN geprüft. Der Schlüssel kommt in die Datei "
            ".env, neben das Bot-Token."
        ),
        "second_reader_test_ok": (
            "✅ Schlüssel akzeptiert: {model} antwortete in {seconds:.1f} s."
        ),
        "second_reader_test_fail": (
            "❌ Zweitleser hat nicht geantwortet:\n{error}\n\n"
            "Der Bot funktioniert trotzdem: er liest die Fotos selbst."
        ),
        "btn_second_reader_test": "🧪 Schlüssel prüfen",
        "ocr_second_opinion_took": (
            "🔎 Der Zweitleser hat den Code gelesen: <code>{vin}</code>\n"
            "Bitte mit dem Typenschild am Fahrzeug vergleichen."
        ),
        "ocr_second_opinion_differs": (
            "🔎 Der Zweitleser sieht <code>{vin}</code>, der Bot las "
            "<code>{local}</code>. Es bleibt die Lesung des Bots — bitte mit "
            "dem Typenschild vergleichen."
        ),
        "ocr_second_opinion_agrees": (
            "🔎 Der Zweitleser bestätigt den Code: <code>{vin}</code>"
        ),
        "ocr_cloud_read": (
            "🔎 Code vom Zweitleser gelesen — bitte mit dem Typenschild vergleichen."
        ),
        "ocr_second_opinion_partial": (
            "🔎 Der Zweitleser hat nicht alles gelesen: <code>{partial}</code>\n"
            "Ein ? steht dort, wo er ein Zeichen nicht lesen konnte."
        ),
        "admin_delete_confirm": (
            "🗑 <b>BENUTZER LÖSCHEN?</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "<b>{name}</b> · ID: <code>{user_id}</code>\n"
            "Rolle: <b>{role}</b>\n\n"
            "🚗 Fahrzeugkarten: <b>{cards}</b>\n"
            "🎨 Lackierungskarten: <b>{paint}</b>\n\n"
            "⚠️ Der Benutzer wird aus dem Bot entfernt. Seine Karten bleiben in "
            "der Datenbank und im Archivkanal. Schreibt er erneut /start, "
            "wird er neu mit der Rolle „Fahrer“ angelegt."
        ),
        "admin_delete_done": (
            "✅ Benutzer <b>{user}</b> gelöscht. Seine Karten ({cards}) bleiben erhalten."
        ),
        "admin_delete_forbidden": "⛔ Dieser Benutzer darf nicht gelöscht werden.",
        "admin_delete_self": "⛔ Sie können sich nicht selbst löschen.",
        "admin_delete_missing": "⚠️ Dieser Benutzer ist nicht mehr in der Datenbank.",
        "access_denied_short": "Zugriff verweigert.",
        "access_denied": (
            "⛔ Kein Zugriff auf diesen Firmen-Bot. Senden Sie dem Administrator "
            "Ihre Telegram-ID: <code>{user_id}</code>"
        ),
        "role_driver": "Fahrer",
        "role_worker": "Mitarbeiter",
        "role_admin": "Administrator",
        "role_superadmin": "Hauptadministrator",
        "welcome_role": "Ihre Rolle: <b>{role}</b>.",
        "role_forbidden": "⛔ Ihre Rolle erlaubt diese Aktion nicht.",
        "admin_forbidden": "⛔ Dieser Bereich ist nur für Administratoren verfügbar.",
        "admin_panel": (
            "🛡 <b>ADMIN-BEREICH</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Ihre Rolle: <b>{role}</b>\n\n"
            "👥 <b>PERSONEN</b>\n"
            "Insgesamt: <b>{users}</b>\n"
            "🛡 Administratoren: <b>{all_admins}</b>\n"
            "👑 davon Hauptadmins: <b>{main_admins}</b>\n"
            "🛡 reguläre: <b>{admins}</b>\n"
            "👷 Mitarbeiter: <b>{workers}</b>\n"
            "🚚 Fahrer: <b>{drivers}</b>\n\n"
            "🚗 <b>KARTEN</b>\n"
            "Aktiv: <b>{active_cards}</b>\n"
            "🗑 Gelöscht: <b>{deleted_cards}</b>\n"
            "📦 Insgesamt: <b>{total_cards}</b>\n\n"
            "🎨 <b>LACKIERUNG</b>\n"
            "In Lackierung: <b>{paint_in_progress}</b>\n"
            "✅ Abgeholt: <b>{paint_completed}</b>\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "admin_users": (
            "👥 <b>BENUTZER UND ROLLEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Seite {page} von {pages} · insgesamt {total}\n\n{users}"
        ),
        "admin_users_empty": "Es sind noch keine Benutzer registriert.",
        "admin_manage_hint": (
            "\n\nDer Hauptadministrator vergibt jede Rolle. Administratoren dürfen "
            "nur zwischen „Mitarbeiter“ und „Fahrer“ wechseln. Beide dürfen jeden "
            "Benutzer der Liste umbenennen. \U0001f5d1 löscht Fahrer und "
            "Mitarbeiter, der Hauptadministrator jeden außer sich selbst."
        ),
        "admin_view_hint": (
            "\n\nDie Rolle eines Hauptadministrators oder Administrators kann hier nicht geändert werden."
        ),
        "admin_role_changed": (
            "✅ Benutzer <b>{user}</b> hat die Rolle „{role}“ erhalten."
        ),
        "admin_user_telegram_note": " (Telegram-Name: {name})",
        "admin_rename_prompt": (
            "✏️ Bitte den neuen Namen für <b>{user}</b> senden.\n"
            "Aktuell wird angezeigt: <b>{name}</b>.\n"
            "Zwischen 2 und 64 Zeichen, mindestens ein Buchstabe oder eine Zahl."
        ),
        "admin_rename_done": "✅ Benutzer <b>{user}</b> heißt jetzt „{name}“.",
        "admin_rename_invalid": (
            "❌ Der Name muss zwischen 2 und 64 Zeichen lang sein und mindestens "
            "einen Buchstaben oder eine Zahl enthalten."
        ),
        "admin_rename_forbidden": "⛔ Sie dürfen diesen Benutzer nicht umbenennen.",
        "admin_role_forbidden": "⛔ Sie dürfen diese Rolle nicht vergeben.",
        "admin_master_protected": "Der Hauptadministrator kann im Bot nicht geändert werden.",
        "admin_user_missing": "Benutzer nicht gefunden. Er muss den Bot zuerst öffnen.",
        "admin_role_changed_hint": "Die neue Rolle erscheint nach /menu im Benutzermenü.",
        "create_vehicle_photo": (
            "🚗 <b>SCHRITT 1 VON 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●○○]\n\n"
            "Bitte ein scharfes Foto des Fahrzeugs senden."
        ),
        "vehicle_photo_required": "Bitte das Fahrzeug ausdrücklich als Foto senden.",
        "photo_too_small": (
            "❌ Das Foto ist zu klein. Bitte ein schärferes Foto mit mindestens "
            "320×240 Pixeln senden."
        ),
        "photo_too_large": "❌ Das Foto ist zu groß. Maximal zulässig sind 10 MB.",
        "vin_photo_too_small": (
            "❌ Der VIN-Ausschnitt ist zu klein. Benötigt wird ein scharfes Bild "
            "mit mindestens 160×50 Pixeln und der vollständigen VIN-Zeile."
        ),
        "photo_reused": (
            "❌ Dieses Foto zeigt das Fahrzeug und wurde im ersten Schritt "
            "verwendet. Für die VIN wird ein Dokumentenfoto benötigt: "
            "der Frachtbrief oder ein Ausschnitt daraus."
        ),
        "create_invoice_photo": (
            "📄 <b>SCHRITT 2 VON 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●○]\n\n"
            "Bitte ein Foto des <b>vollständigen Belegs</b> senden. "
            "Der Beleg wird gespeichert und ist in der Fahrzeugkarte abrufbar."
        ),
        "invoice_photo_required": "Bitte ein Foto des vollständigen Belegs senden.",
        "create_vin_photo": (
            "🔢 <b>SCHRITT 3 VON 3</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●●]\n\n"
            "Senden Sie ein Foto, auf dem die VIN zu sehen ist.\n\n"
            "Ein <b>beschnittener, großer Ausschnitt</b> wird am "
            "zuverlässigsten gelesen. Der <b>komplette Frachtbrief</b> geht "
            "ebenfalls: noch einmal senden oder die Taste unten drücken — "
            "der Bot findet den Code selbst."
        ),
        "btn_use_invoice": "📄 VIN aus dem Frachtbrief",
        "vin_photo_required": "Bitte ein Foto mit der VIN/FIN senden.",
        "ocr_processing": "🔍 VIN/FIN wird auf dem Foto erkannt…",
        "ocr_found": (
            "Erkannte VIN — mit einem Antippen kopierbar:\n\n"
            "<pre>{vin_display}</pre>\n"
            "Letzte 6 Zeichen: <b>{suffix}</b>\n\n"
            "Vor dem Speichern alle 17 Zeichen mit dem Foto vergleichen. "
            "Stimmt ein Zeichen nicht, „Ein Zeichen korrigieren“ drücken."
        ),
        "ocr_not_found": (
            "⚠️ Die vollständige VIN konnte nicht sicher erkannt werden.\n"
            "Ist der Code auf dem Foto vorhanden, aber unleserlich: "
            "formatfüllend, scharf und ohne Blitzreflexe fotografieren, "
            "sodass die FIN die halbe Aufnahme einnimmt.\n"
            "Jetzt die <b>vollständige VIN (17 Zeichen)</b> oder die "
            "<b>letzten 6 Zeichen</b> manuell eingeben."
        ),
        "ocr_partial": (
            "🔎 FIN nicht vollständig gelesen: die Zeichen <b>{positions}</b> "
            "waren nicht zu entziffern. Der Rest steht — bitte nur diese "
            "ergänzen.\n\n"
            "<pre>{vin}</pre>\n\n"
            "Ein „?“ bedeutet: die Kamera konnte das Zeichen nicht erkennen. "
            "Es wird nicht geraten — bitte mit dem Typenschild vergleichen "
            "und auf die Zeichennummer tippen."
        ),
        "ocr_retake": ("📷 <b>Bitte neu fotografieren.</b> {instructions}"),
        "vin_has_gaps": (
            "Der Code enthält noch unausgefüllte Zeichen. Bitte ergänzen "
            "oder die FIN vollständig eingeben."
        ),
        "ocr_weak": (
            "⚠️ Das Foto ist unscharf, die FIN wurde unsicher erkannt. "
            "Bitte jedes Zeichen prüfen und mit dem Typenschild abgleichen. "
            "Bei Abweichungen „Korrigieren“ drücken."
        ),
        "ocr_check_digit": (
            "⚠️ FIN erkannt, aber die Prüfziffer stimmt nicht: mindestens "
            "ein Zeichen wurde falsch erkannt. Bitte jedes Zeichen mit dem "
            "Typenschild abgleichen. Bei Abweichungen „Korrigieren“ drücken."
        ),
        "ocr_no_text": (
            "\U0001f4f7 Auf dem Foto ist kein Text lesbar. "
            "Bitte die VIN formatf\u00fcllend und ohne "
            "Blitzreflexe fotografieren: Typenschild unter der "
            "Windschutzscheibe oder Aufkleber in der Fahrert\u00fcr. "
            "Jetzt die <b>vollst\u00e4ndige VIN (17 Zeichen)</b> oder die "
            "<b>letzten 6 Zeichen</b> eingeben."
        ),
        "ocr_unavailable": (
            "⚠️ Die Texterkennung ist derzeit nicht verfügbar. Bitte die vollständige "
            "VIN (17 Zeichen) oder die letzten 6 Zeichen manuell eingeben."
        ),
        "ocr_fix_which": (
            "Welches Zeichen ist falsch? Bitte antippen.\n\n"
            "Mit „?“ markierte Zeichen wurden unterschiedlich gelesen — "
            "dort beginnen."
        ),
        "ocr_fix_replace": (
            "Zeichen {position}: jetzt „{current}“. Womit ersetzen?\n\n"
            "Passende Zeichen — mit ihnen stimmt die Prüfziffer — "
            "sind mit einem Punkt markiert."
        ),
        "ocr_fix_hint": (
            "Wahrscheinlich wurde Zeichen {position} als „{current}“ gelesen, "
            "richtig ist „{fixed}“: nur dann stimmt die Prüfziffer."
        ),
        "ocr_fix_done": (
            "Zeichen {position} durch „{char}“ ersetzt.\n\n"
            "<pre>{vin}</pre>\n\n"
            "Bitte die übrigen Zeichen mit dem Typenschild vergleichen."
        ),
        "manual_vin_prompt": (
            "Vollständige VIN (17 Zeichen) oder die letzten 6 Zeichen eingeben. "
            "Erlaubt sind lateinische Buchstaben und Ziffern.\n\n"
            "Der Code lässt sich aus der Nachricht oben kopieren und ein "
            "Zeichen darin korrigieren — schneller als neu tippen."
        ),
        "vin_invalid": (
            "❌ Ungültiges Format. Erforderlich sind genau <b>17</b> oder <b>6</b> "
            "lateinische Buchstaben/Ziffern. I, O und Q werden in VINs nicht verwendet. "
            "Zusätzlicher Text ist nicht zulässig."
        ),
        "text_too_long": "❌ Der Wert ist zu lang. Bitte Eingabe prüfen und erneut senden.",
        "duplicate": (
            "⚠️ Ein Fahrzeug mit dieser vollständigen VIN ist bereits als Karte "
            "#{card_id} vorhanden. Es wurde keine neue Karte angelegt."
        ),
        "card_saved": (
            "✅ <b>KARTE ANGELEGT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Kartennummer: <b>#{card_id}</b>\n\n"
            "Sie ist sofort über die VIN-Suche zu finden."
        ),
        "search_prompt": (
            "🔎 <b>NACH VIN SUCHEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Die letzten <b>4 oder 6</b> Zeichen der VIN oder\n"
            "die ganze FIN eingeben.\n\n"
            "Alternativ ein Foto der vollständigen VIN senden; der Bot erkennt sie und sucht."
        ),
        "search_invalid": (
            "❌ Bitte 4, 6 oder 17 Zeichen eingeben: die letzten \n"
            "Zeichen der VIN oder die ganze FIN. Oder ein VIN-Foto senden."
        ),
        "search_photo_failed": (
            "Die vollständige VIN konnte auf dem Foto nicht erkannt werden. Bitte ein "
            "anderes Foto senden oder die letzten 4/6 Zeichen manuell eingeben."
        ),
        "no_results": (
            "🔍 <b>KEINE TREFFER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Für die VIN-Endung <b>{query}</b> gibt es keine Karte."
        ),
        "all_empty": (
            "📂 <b>NOCH KEINE KARTEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Legen Sie die erste Karte mit „➕ Fahrzeug anlegen“ an."
        ),
        "cancelled": (
            "↩️ <b>ABGEBROCHEN</b>\n━━━━━━━━━━━━━━━━━━\n\nJederzeit neu beginnen."
        ),
        "settings": (
            "🌐 <b>SPRACHE UND EINSTELLUNGEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Ihre Rolle: <b>{role}</b>\n\n"
            "Sprache der Benutzeroberfläche wählen:"
        ),
        "help": (
            "❓ <b>SCHNELLHILFE</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "1️⃣ „➕ Fahrzeug anlegen“\n"
            "Drei Fotos: Fahrzeug, Beleg,\n"
            "separater VIN-Ausschnitt.\n\n"
            "2️⃣ „🔎 Nach VIN suchen“\n"
            "Die letzten 4 oder 6 Zeichen\n"
            "oder ein Foto der VIN.\n\n"
            "3️⃣ „🎨 Lackierung“\n"
            "Fahrzeug abgeben, ansehen,\n"
            "was läuft, und abholen.\n\n"
            "4️⃣ „📖 Anleitung“\n"
            "Alle Regeln Schritt für Schritt,\n"
            "inklusive Prüfungen.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Befehle:\n"
            "/menu — Menü, /manual — Anleitung,\n"
            "/cancel — Abbrechen, /help — Hilfe."
        ),
        "unknown": "Bitte die Schaltflächen im Hauptmenü verwenden.",
        "card_title": "🚗 <b>Fahrzeugkarte #{card_id}</b>",
        "card_vin": "🔢 VIN: <code>{masked_vin}</code>",
        "card_search_keys": "🔎 Suche: <b>{suffix6}</b> oder <b>{suffix4}</b>",
        "card_owner": "👤 Erfasst von: {owner}",
        "card_date": "📅 Datum: {date}",
        "card_position": "📄 Treffer: {position} von {total}",
        "card_invoice_view": "📄 <b>Beleg zur Fahrzeugkarte #{card_id}</b>",
        "delete_question": "Karte #{card_id} löschen? Sie wird danach nicht mehr gefunden.",
        "deleted": (
            "🗑 <b>KARTE GELÖSCHT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Kartennummer: <b>#{card_id}</b>\n\n"
            "In der Suche erscheint sie nicht mehr."
        ),
        "delete_forbidden": "Nur Administratoren dürfen Karten löschen.",
        "already_deleted": "Die Karte wurde bereits gelöscht oder existiert nicht.",
        "stale_button": ("Dieses Menü ist veraltet. Bitte neu öffnen."),
        "operation_expired": "Diese Aktion ist abgelaufen. Bitte im Hauptmenü neu beginnen.",
        "paint_menu": (
            "🎨 <b>LACKIERUNG</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📥 <b>In Lackierung geben</b>\n"
            "Zwei Fotos: Fahrzeug und VIN.\n\n"
            "📋 <b>In Lackierung</b>\n"
            "Fahrzeuge, die gerade lackiert werden,\n"
            "mit „Aus Lackierung abgeholt“.\n\n"
            "✅ <b>Abgeholt</b>\n"
            "Fahrzeuge, die bereits abgeholt sind.\n\n"
            "🔎 <b>Nach VIN suchen</b>\n"
            "Fahrzeug finden und Abholung merken.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "paint_create_vehicle_photo": (
            "🎨 <b>SCHRITT 1 VON 2</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●○]\n\n"
            "Bitte ein Foto des Fahrzeugs senden, das in Lackierung gegeben wird."
        ),
        "paint_vehicle_photo_required": (
            "Bitte ausdrücklich ein Foto des Fahrzeugs senden, keinen Text."
        ),
        "paint_create_vin_photo": (
            "🔢 <b>SCHRITT 2 VON 2</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "[●●]\n\n"
            "Bitte einen <b>zugeschnittenen VIN-Ausschnitt</b> dieses Fahrzeugs senden.\n\n"
            "„Fahrgestell-Nummer“ oder „Fahrzeug-Identifizierungsnummer“ und die "
            "vollständige 17-stellige VIN müssen sichtbar sein. Erstes und letztes "
            "Zeichen nicht abschneiden."
        ),
        "paint_vin_photo_required": "Bitte ein zugeschnittenes VIN-Foto senden.",
        "paint_search_prompt": (
            "🔎 <b>NACH VIN SUCHEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Die letzten <b>4 oder 6</b> Zeichen der VIN oder\n"
            "die ganze FIN eingeben.\n\n"
            "Gesucht wird im Bereich „Lackierung“: Fahrzeuge in Lackierung und "
            "bereits abgeholte. Alternativ ein VIN-Foto senden."
        ),
        "paint_saved": (
            "✅ <b>FAHRZEUG IN LACKIERUNG</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Kartennummer: <b>#{card_id}</b>\n\n"
            "Es steht unter „📋 In Lackierung“."
        ),
        "paint_duplicate": (
            "⚠️ Dieses Fahrzeug ist bereits als Karte #{card_id} in Lackierung. "
            "Es wurde kein zweiter Eintrag erstellt."
        ),
        "paint_empty": "📋 Aktuell ist kein Fahrzeug in Lackierung.",
        "paint_done_empty": "✅ Die Liste der abgeholten Fahrzeuge ist leer.",
        "paint_no_results": (
            "In der Lackierung wurde nichts zur VIN-Endung <b>{query}</b> gefunden."
        ),
        "paint_card_title": "🎨 <b>Lackierung #{card_id}</b>",
        "paint_status_in": "Status: <b>in Lackierung</b>",
        "paint_status_done": "Status: <b>lackiert, abgeholt</b>",
        "paint_card_sent": "In Lackierung gegeben von: {owner}",
        "paint_card_taken": "Aus Lackierung abgeholt von: {owner}",
        "paint_card_taken_date": "Abholdatum: {date}",
        "paint_card_vin_view": "🔢 <b>VIN zur Lackierungskarte #{card_id}</b>",
        "paint_take_question": (
            "Fahrzeug aus der Lackierung abgeholt?\n"
            "Karte #{card_id} verschwindet aus „In Lackierung“ und erscheint unter "
            "„Lackiert · abgeholt“."
        ),
        "paint_taken": (
            "✅ Karte #{card_id} wurde nach „Lackiert · abgeholt“ verschoben."
        ),
        "paint_already_taken": "Dieses Fahrzeug wurde bereits aus der Lackierung abgeholt.",
        "btn_admin_backup": "💾 Sicherungen",
        "backup_title": (
            "💾 <b>SICHERUNGEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🗂 Kopien auf dem Server: <b>{snapshots}</b>\n"
            "🕓 Letzte: <b>{last}</b>\n"
            "📦 Datenbank: <b>{size}</b>\n"
            "♻️ Im Papierkorb: <b>{trash}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Datenbank exportieren, wieder\n"
            "einspielen oder zurücksetzen.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_last_never": "noch keine",
        "btn_backup_export": "📤 Datenbank exportieren",
        "btn_backup_import": "📥 Datenbank einspielen",
        "btn_backup_rollback": "🕘 Zurücksetzen",
        "btn_backup_trash": "♻️ Papierkorb",
        "btn_backup_journal": "📜 Protokoll",
        "backup_export_caption": (
            "💾 <b>DATENBANK</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "📅 {date}\n"
            "📦 Größe: {size}\n\n"
            "Diese Datei lässt sich über\n"
            "„📥 Datenbank einspielen“ zurückholen."
        ),
        "backup_export_failed": (
            "❌ Die Datenbankdatei konnte nicht\n"
            "erstellt werden. Bitte später erneut versuchen."
        ),
        "backup_import_prompt": (
            "📥 <b>DATENBANK EINSPIELEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Bitte die frühere Datenbankdatei\n"
            "senden (.db oder .db.gz).\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Der Bot sichert die aktuelle\n"
            "Datenbank vorher automatisch.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_received": (
            "📥 <b>DATEIPRÜFUNG</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "In der Datei:\n"
            "🗂 Karteikarten: <b>{cards}</b>\n"
            "👥 Benutzer: <b>{users}</b>\n"
            "📦 Größe: {size}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Aktuelle Datenbank ersetzen?\n"
            "Derzeit: {current_cards} Karteikarten.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_bad": (
            "❌ <b>DATEI PASST NICHT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{reason}\n\n"
            "Andere Datei senden oder\n"
            "„{cancel}“ drücken."
        ),
        "backup_import_done": (
            "✅ <b>DATENBANK EINGESPIELT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🗂 Karteikarten: <b>{cards}</b>\n"
            "👥 Benutzer: <b>{users}</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Vorherige Datenbank gesichert als:\n"
            "🗂 {snapshot}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_import_failed": (
            "❌ Einspielen fehlgeschlagen.\nDie Datenbank bleibt unverändert."
        ),
        "btn_backup_apply": "✅ Ja, ersetzen",
        "backup_list_title": (
            "🕘 <b>ZURÜCKSETZEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Bitte den Tag wählen, auf den\n"
            "die Datenbank zurückgesetzt wird.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Seite {page} von {pages}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "backup_list_empty": (
            "🕘 <b>ZURÜCKSETZEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Es gibt noch keine Kopie.\n"
            "Der Bot erstellt sie jeden Tag selbst."
        ),
        "backup_page_label": "Seite {page} von {pages}",
        "backup_confirm": (
            "🕘 <b>ZURÜCKSETZEN BESTÄTIGEN</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Datenbank auf {label} zurücksetzen?\n\n"
            "Alles, was danach angelegt wurde,\n"
            "geht dabei verloren.\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "btn_yes_rollback": "🕘 Ja, zurücksetzen",
        "backup_restored": (
            "✅ <b>ZURÜCKGESETZT</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Stand: {label}\n\n"
            "🗂 Karteikarten: <b>{cards}</b>\n"
            "👥 Benutzer: <b>{users}</b>\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_title": (
            "♻️ <b>PAPIERKORB</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Gelöschte Karteikarten: <b>{total}</b>\n\n"
            "Eine Karte lässt sich zurückholen.\n"
            "Endgültig löschen darf man sie\n"
            "erst nach {days} Tagen.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "{page_label}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_empty": (
            "♻️ <b>PAPIERKORB IST LEER</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Gelöschte Karteikarten landen hier\n"
            "und bleiben {days} Tage erhalten."
        ),
        "trash_card": (
            "♻️ <b>GELÖSCHTE KARTE #{card_id}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔑 VIN: <code>{vin}</code>\n"
            "👤 Angelegt von: {owner}\n"
            "🗑 Gelöscht von: {deleter}\n"
            "🕓 Wann: {date}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "trash_deleter_unknown": "unbekannt",
        "btn_restore": "♻️ Wiederherstellen",
        "btn_purge": "🔥 Endgültig löschen",
        "trash_restored": "✅ Karteikarte Nr.{card_id} wiederhergestellt.",
        "trash_purged": "🔥 Karteikarte Nr.{card_id} endgültig gelöscht.",
        "trash_purge_too_early": (
            "⏳ Endgültiges Löschen ist erst\n{days} Tage nach dem Löschen möglich."
        ),
        "trash_purge_forbidden": (
            "⛔ Nur der Hauptadministrator darf\nKarteikarten endgültig löschen."
        ),
        "trash_already": "Diese Karteikarte ist schon wiederhergestellt.",
        "trash_list_title": (
            "♥️ <b>PAPIERKORB</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{headline}\n"
            "{filter}"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{lines}\n\n"
            "Seite {page} von {pages}. Karte antippen,\n"
            "um sie zu öffnen."
        ),
        "trash_list_total": "Gelöschte Karten: <b>{total}</b>",
        "trash_list_found": "Gefunden: <b>{total}</b>",
        "trash_list_line": "{index}. Nr.{card_id} · <code>{vin}</code> · {date} · {owner}",
        "trash_list_button": "Nr.{card_id} · {vin} · {date} · {owner}",
        "btn_trash_find": "🔍 Suchen",
        "btn_trash_clear": "❌ Suche zurücksetzen",
        "btn_trash_back_list": "⬅️ Zur Liste",
        "trash_find_prompt": (
            "🔍 <b>SUCHE IM PAPIERKORB</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Die letzten 4–6 Zeichen der FIN, die ganze\n"
            "FIN oder ein Teil des Namens von dem,\n"
            "der die Karte angelegt hat."
        ),
        "trash_find_invalid": (
            "So kann ich nicht suchen. Bitte 3 bis 64\nZeichen: FIN oder Name."
        ),
        "trash_filter_active": "Filter: <b>{query}</b>",
        "trash_nothing_found": ("Im Papierkorb ist nichts zu «{query}»."),
        "trash_search_cleared": "Suche zurückgesetzt.",
        "journal_title": (
            "📜 <b>PROTOKOLL</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Wer hat was mit der Datenbank getan.\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "{entries}\n"
            "━━━━━━━━━━━━━━━━━━"
        ),
        "journal_empty": "Noch keine Einträge.",
        "journal_entry": "{icon} {action}\n👤 {actor} · 🕓 {date}",
        "audit_card_created": "Karte angelegt",
        "audit_card_deleted": "Karte gelöscht",
        "audit_card_restored": "Karte wiederhergestellt",
        "audit_card_purged": "Karte vernichtet",
        "audit_backup_created": "Kopie erstellt",
        "audit_backup_exported": "Datenbank exportiert",
        "audit_backup_uploaded": "Datenbank eingespielt",
        "audit_backup_restored": "Zurückgesetzt",
        "audit_role_changed": "Rolle geändert",
        "audit_user_renamed": "Umbenannt",
        "audit_unknown": "Aktion",
        "backup_no_sqlite": ("❌ Sicherungen gibt es nur für\neine SQLite-Datenbank."),
        "backup_forbidden": "⛔ Dieser Bereich ist nur für Administratoren.",
        "backup_import_need_file": "Es wird eine Datenbankdatei (.db oder .db.gz) benötigt.",
        "backup_import_error": "Die Datei konnte nicht gelesen werden.",
        "operation_cancelled": "↩️ Abgebrochen.",
    },
}


def t(language: str | None, key: str, **kwargs: object) -> str:
    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    template = TEXTS[lang].get(key) or TEXTS[DEFAULT_LANGUAGE][key]
    return template.format(**kwargs)


def all_labels(key: str) -> set[str]:
    return {translations[key] for translations in TEXTS.values()}
