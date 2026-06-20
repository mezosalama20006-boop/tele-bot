import logging
import asyncio


# ── Fix for asyncio loop issues (Python 3.14) ──

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

from database import Database
from config import BOT_TOKEN, ADMIN_IDS, EGP_EXCHANGE_RATE, DATABASE_PATH

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

db = Database(DATABASE_PATH)


# ── States ─────────────────────────────────────────────────
WAITING_PAYMENT_AMOUNT      = 1
WAITING_PAYMENT_PROOF       = 2
WAITING_PRODUCT_NAME        = 3
WAITING_PRODUCT_DESC        = 4
WAITING_PRODUCT_PRICE       = 5
WAITING_ITEM_CONTENT        = 6
WAITING_ADD_BALANCE_AMOUNT  = 7
WAITING_CATEGORY_NAME       = 8
WAITING_CATEGORY_EMOJI      = 9
WAITING_APP_NAME            = 10
WAITING_APP_EMOJI           = 11
WAITING_BROADCAST_MESSAGE   = 12
WAITING_PURCHASE_QUANTITY   = 13
WAITING_PRODUCT_TYPE         = 14
WAITING_PRODUCT_INPUT_PROMPT = 15
WAITING_PURCHASE_INPUT       = 16
WAITING_ADMIN_BALANCE_EDIT   = 17


def is_admin(user_id):
    return user_id in ADMIN_IDS

# ── Keyboards ──────────────────────────────────────────────

def persistent_keyboard():
    return ReplyKeyboardMarkup([
        ["🛍️ المنتجات", "💼 محفظتي"],
        ["➕ شحن رصيد", "📋 طلباتي"],
        ["ℹ️ مساعدة"]
    ], resize_keyboard=True, is_persistent=True)

def format_price_summary(price, quantity=1):
    total_price = price * quantity
    egp_price = price * EGP_EXCHANGE_RATE
    egp_total = total_price * EGP_EXCHANGE_RATE
    return (
        f"💰 السعر لكل 1000: *${price:.2f}*\n"
        f"💴 السعر بالمصري لكل 1000: *{egp_price:.2f} جنيه*\n"
        f"💵 السعر الإجمالي: *${total_price:.2f}* / *{egp_total:.2f} جنيه*"
    )


def main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("🛍️ المنتجات",   callback_data="categories"),
         InlineKeyboardButton("💼 محفظتي",      callback_data="wallet")],
        [InlineKeyboardButton("➕ شحن رصيد",    callback_data="add_balance"),
         InlineKeyboardButton("📋 طلباتي",      callback_data="my_orders")],
        [InlineKeyboardButton("ℹ️ مساعدة",      callback_data="help")]
    ]
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الإدارة", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

async def notify_admin_order(context, user, product_name, quantity, user_input=None, price=None):
    text = (
        f"🛒 *طلب جديد*\n"
        f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 `{user.id}`\n"
        f"📦 الخدمة: *{product_name}*\n"
        f"🔢 الكمية: *{quantity}*\n"
    )
    if price is not None:
        total_price = price * quantity
        text += f"💰 السعر الإجمالي: *${total_price:.2f}*\n"
    if user_input:
        text += f"📎 الرابط/الحساب المرسل: `{user_input}`\n"
    else:
        text += "📎 لا يوجد رابط من المستخدم. هذه خدمة يتم تسليمها من الإدارة.\n"
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

async def notify_admin_speed_request(context, user, purchase_id, product_name, quantity):
    text = (
        f"🚀 *طلب تسريع جديد*\n"
        f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 `{user.id}`\n"
        f"🔢 الطلب: *#{purchase_id}*\n"
        f"📦 الخدمة: *{product_name}*\n"
        f"🔢 الكمية: *{quantity}*\n"
        f"📌 هذه الخدمة طلبت تسريعًا من المستخدم"
    )
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

def admin_panel_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 الكاتيجريز", callback_data="admin_categories"),
            InlineKeyboardButton("📦 المنتجات", callback_data="admin_products_all")
        ],
        [
            InlineKeyboardButton("📥 الطلبات", callback_data="admin_orders"),
            InlineKeyboardButton("� المستخدمين", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("� تسريعات", callback_data="admin_speed_requests"),
            InlineKeyboardButton("💳 الإيداعات", callback_data="admin_deposits")
        ],
        [
            InlineKeyboardButton("📊 إحصائيات", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")
        ],
        [
            InlineKeyboardButton("📢 رسالة جماعية", callback_data="admin_broadcast")
        ]
    ])


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    # pagination: admin_orders or admin_orders_{page}
    parts = (query.data or "").split("_")
    page = 1
    if len(parts) >= 3:
        try:
            page = int(parts[2])
            if page < 1:
                page = 1
        except:
            page = 1

    page_size = 8
    rows = db.get_purchases(limit=page_size + 1, offset=(page - 1) * page_size)
    has_next = len(rows) > page_size
    orders = rows[:page_size]

    if not orders:
        await query.edit_message_text(
            "📥 *الطلبات*\n\n_لا توجد طلبات في هذه الصفحة._",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]))
        return

    text = f"📥 *الطلبات — صفحة {page}*\n━━━━━━━━━━━━━━━━━━\n"
    for o in orders:
        udisplay = f"{o.get('user_name')} (@{o.get('username')})" if o.get('username') else f"{o.get('user_name') or 'N/A'}"
        content_preview = ''
        # peek first few item contents
        items = []
        try:
            items = db.get_purchase(o.get('id'))['items']
        except:
            items = []
        if items:
            content_preview = items[0].get('content','')
        if len(content_preview) > 64:
            content_preview = content_preview[:61] + '...'
        user_input = o.get('user_input') or '_لا يوجد_'
        quantity = o.get('quantity', 1)
        full_title = f"{o.get('category_name', '')} › {o.get('app_name', '')} › {o.get('product_name', '')}"
        text += (
            f"\n🔢 #{o.get('id')} — *{full_title}*\n"
            f"👤 {udisplay} — 🆔 `{o.get('user_id')}`\n"
            f"📅 {o.get('date')} — 📦 الكمية: *{quantity}*\n"
            f"💰 الإجمالي: *${o.get('total_price'):.2f}*\n"
            f"📎 الرابط/الحساب المرسل: `{user_input}`\n"
        )
        # add action button row per order
        if o.get('status') == 'completed':
            text += "   ✅ الحالة: *مكتمل*\n"
            # no action button for completed
            # but provide a detail button
            if 'keyboard_rows' not in locals():
                keyboard_rows = []
            keyboard_rows.append([InlineKeyboardButton(f"🔎 تفاصيل #{o.get('id')}", callback_data=f"order_detail_{o.get('id')}")])
        else:
            if 'keyboard_rows' not in locals():
                keyboard_rows = []
            keyboard_rows.append([
                InlineKeyboardButton(f"✅ أكمل #{o.get('id')}", callback_data=f"complete_order_{o.get('id')}"),
                InlineKeyboardButton(f"❌ رفض #{o.get('id')}", callback_data=f"reject_purchase_{o.get('id')}"),
                InlineKeyboardButton(f"🔎 تفاصيل #{o.get('id')}", callback_data=f"order_detail_{o.get('id')}")
            ])
        text += "━━━━━━━━━━━━━━━━━━\n"

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"admin_orders_{page-1}"))
    nav.append(InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel"))
    if has_next:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"admin_orders_{page+1}"))

    # combine keyboard_rows and nav
    kb = []
    if 'keyboard_rows' in locals():
        kb.extend(keyboard_rows)
    kb.append(nav)

    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.username or user.first_name, user.first_name)
    text = (
        f"👋 أهلاً *{user.first_name}*!\n\n"
        "🏪 *متجر المنتجات الرقمية*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🛍️ تصفح منتجاتنا الرقمية\n"
        "💰 أدر رصيدك بسهولة\n"
        "📦 تسليم فوري بعد الشراء\n\n"
        "اختر من القائمة:"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=persistent_keyboard())
        await update.message.reply_text("📋 *القائمة الرئيسية*", parse_mode='Markdown',
                                        reply_markup=main_menu_keyboard(user.id))
    else:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown',
                                                      reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))
        await update.callback_query.message.reply_text("📋 *القائمة الرئيسية*", parse_mode='Markdown',
                                                       reply_markup=main_menu_keyboard(user.id))

# ══════════════════════════════════════════════════════════
# HANDLE MAIN MENU TEXT BUTTONS
# ══════════════════════════════════════════════════════════

async def handle_main_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🛍️ المنتجات":
        await show_categories(update, context)
    elif text == "💼 محفظتي":
        await show_wallet_text(update, context)
    elif text == "➕ شحن رصيد":
        await add_balance_start_text(update, context)
    elif text == "📋 طلباتي":
        await show_orders_text(update, context)
    elif text == "ℹ️ مساعدة":
        await show_help_text(update, context)

# ══════════════════════════════════════════════════════════
# CATEGORIES (Level 1)
# ══════════════════════════════════════════════════════════

async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
    categories = db.get_all_categories()
    if not categories:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "📂 *لا توجد كاتيجريز بعد.*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))
        else:
            await update.message.reply_text(
                "📂 *لا توجد كاتيجريز بعد.*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))
        return
    keyboard = []
    for cat in categories:
        keyboard.append([InlineKeyboardButton(
            f"{cat['emoji']} {cat['name']}",
            callback_data=f"cat_{cat['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "🛍️ *اختر الكاتيجري:*\n━━━━━━━━━━━━━━━━━━",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            "🛍️ *اختر الكاتيجري:*\n━━━━━━━━━━━━━━━━━━",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

# ══════════════════════════════════════════════════════════
# APPS (Level 2)
# ══════════════════════════════════════════════════════════

async def show_apps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[1])
    cat = db.get_category(cat_id)
    apps = db.get_apps_by_category(cat_id)
    if not apps:
        await query.edit_message_text(
            f"{cat['emoji']} *{cat['name']}*\n\nلا توجد تطبيقات بعد.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="categories")]]))
        return
    keyboard = []
    for app in apps:
        keyboard.append([InlineKeyboardButton(
            f"{app['emoji']} {app['name']}",
            callback_data=f"app_{app['id']}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="categories")])
    await query.edit_message_text(
        f"{cat['emoji']} *{cat['name']}*\n━━━━━━━━━━━━━━━━━━\nاختر التطبيق:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ══════════════════════════════════════════════════════════
# PRODUCTS (Level 3)
# ══════════════════════════════════════════════════════════

async def show_products_by_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts  = query.data.split("_")
    app_id = int(parts[1])
    cat_id = int(parts[2])
    app      = db.get_app(app_id)
    products = db.get_products_by_app(app_id)
    if not products:
        await query.edit_message_text(
            f"{app['emoji']} *{app['name']}*\n\nلا توجد خدمات بعد.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cat_{cat_id}")]]))
        return
    keyboard = []
    for p in products:
        emoji = "🟢" if p['stock'] != 0 else "🔴"
        # Show infinity symbol for products with infinite stock or that require input
        if p.get('requires_input') or p['stock'] < 0:
            stock_display = "♾️ لا محدود"
        else:
            stock_display = str(p['stock']) + " متوفر"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {p['name']} — ${p['price']:.2f} ({stock_display})",
            callback_data=f"product_{p['id']}_{app_id}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"cat_{cat_id}")])
    await query.edit_message_text(
        f"{app['emoji']} *{app['name']}*\n━━━━━━━━━━━━━━━━━━\nاختر الخدمة:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ══════════════════════════════════════════════════════════
# PRODUCT DETAIL
# ══════════════════════════════════════════════════════════

async def show_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")   # product_{id}_{app_id}_{cat_id}
    product_id = int(parts[1])
    app_id     = int(parts[2])
    cat_id     = int(parts[3])
    product = db.get_product(product_id)
    if not product:
        await query.answer("المنتج غير موجود!", show_alert=True)
        return
    # For products that require input or have infinite stock, show infinity symbol
    if product.get('requires_input') or product['stock'] < 0:
        stock_text = "✅ متوفر ♾️ لا محدود"
    elif product['stock'] > 0:
        stock_text = f"✅ متوفر ({product['stock']} قطعة)"
    else:
        stock_text = "❌ نفد المخزون"
    text = (
        f"📦 *{product['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 {product['description']}\n\n"
        f"💰 السعر: *${product['price']:.2f}*\n"
        f"💴 السعر بالمصري لكل 1000: *{product['price'] * EGP_EXCHANGE_RATE:.2f} جنيه*\n"
        f"📊 الحالة: {stock_text}"
    )
    if product.get('requires_input'):
        # show single-word instruction per user request
        text += f"\n\n📌 أرسل الرابط"
    elif product.get('infinite_stock'):
        text += "\n\n♾️ هذه الخدمة متاحة بعدد لانهائي."
    keyboard = []
    if product['stock'] != 0:
        keyboard.append([InlineKeyboardButton(
            f"🛒 اشتري الآن — ${product['price']:.2f}",
            callback_data=f"buy_{product_id}_{app_id}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"app_{app_id}_{cat_id}")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

# ══════════════════════════════════════════════════════════
# BUY
# ══════════════════════════════════════════════════════════

async def buy_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")
    product_id = int(parts[1])
    app_id     = int(parts[2])
    cat_id     = int(parts[3])
    user_id    = query.from_user.id
    product = db.get_product(product_id)
    balance = db.get_balance(user_id)
    if not product or product['stock'] == 0:
        await query.answer("❌ نفد المخزون!", show_alert=True)
        return

    affordable_qty = int(balance // product['price'])
    max_qty = affordable_qty if product['stock'] < 0 else min(product['stock'], affordable_qty)
    if max_qty == 0:
        shortage = product['price'] - balance
        await query.edit_message_text(
            f"❌ *رصيد غير كافٍ*\n\n"
            f"💰 رصيدك: *${balance:.2f}*\n"
            f"💳 سعر المنتج: *${product['price']:.2f}*\n"
            f"⚠️ تحتاج: *${shortage:.2f}* إضافية",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ شحن رصيد", callback_data="add_balance")],
                [InlineKeyboardButton("🔙 رجوع",       callback_data=f"app_{app_id}_{cat_id}")]
            ]))
        return

    keyboard = []
    for qty in range(1, min(max_qty, 5) + 1):
        keyboard.append([InlineKeyboardButton(str(qty), callback_data=f"setqty_{product_id}_{app_id}_{cat_id}_{qty}")])
    if max_qty > 5:
        keyboard.append([InlineKeyboardButton("📥 أدخل كمية أخرى", callback_data=f"enterqty_{product_id}_{app_id}_{cat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"app_{app_id}_{cat_id}")])

    context.user_data['pending_purchase'] = {
        'product_id': product_id,
        'app_id': app_id,
        'cat_id': cat_id,
        'max_qty': max_qty
    }

    available_text = "♾️ لا محدود" if (product.get('requires_input') or product['stock'] < 0) else str(product['stock'])
    msg_text = f"🛒 *اختر الكمية*\n\n"
    if product.get('requires_input'):
        msg_text += "⚠️ *ملاحظة مهمة:* هذه الخدمة بتطلب الرابط بتاعك بعد الشراء.\n\n"
    msg_text += (
        f"📦 المنتج: *{product['name']}*\n"
        f"{format_price_summary(product['price'])}\n"
        f"📊 المتوفر: *{available_text}*\n"
        f"💵 رصيدك: *${balance:.2f}*\n\n"
        f"اختر الكمية باستخدام الأزرار أدناه أو اضغط أدخل كمية أخرى."
    )
    await query.edit_message_text(msg_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")
    product_id = int(parts[1])
    app_id     = int(parts[2])
    cat_id     = int(parts[3])
    quantity   = int(parts[4])
    user_id    = query.from_user.id
    product = db.get_product(product_id)
    balance = db.get_balance(user_id)
    
    # if product requires input (link), don't purchase yet - just ask for link
    if product.get('requires_input'):
        # save purchase info for later (after receiving link)
        context.user_data['pending_purchase_data'] = {
            'product_id': product_id,
            'quantity': quantity,
            'app_id': app_id,
            'cat_id': cat_id
        }
        context.user_data['state'] = WAITING_PURCHASE_INPUT
        await query.edit_message_text(
            f"✅ *تم حفظ الشراء!*\n\n"
            f"📦 المنتج: *{product['name']}*\n"
            f"🔢 الكمية: *{quantity}*\n"
            f"{format_price_summary(product['price'], quantity)}\n\n"
            f"📎 الآن ابعت الرابط بتاعك:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]))
        return
    
    # for non-link-required products, purchase now
    user_input = context.user_data.get('pending_purchase', {}).get('user_input', None)
    success, result = db.purchase_product(user_id, product_id, quantity, user_input)
    context.user_data.pop('pending_purchase', None)
    if success:
        await notify_admin_order(context, query.from_user, result['product_name'], quantity, user_input, price=product['price'] if product else None)
        await query.edit_message_text(
            f"✅ *تمت عملية الشراء بنجاح!*\n\n"
            f"📦 المنتج: *{result['product_name']}*\n"
            f"🔢 الكمية: *{quantity}*\n"
            f"💵 الرصيد المتبقي: *${result['new_balance']:.2f}*\n\n"
            f"🎁 *تفاصيل المنتجات:*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{result['content']}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]]))
    else:
        await query.edit_message_text(
            f"❌ *فشل الشراء*\n\n{result}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"app_{app_id}_{cat_id}")]]))

async def select_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")
    product_id = int(parts[1])
    app_id     = int(parts[2])
    cat_id     = int(parts[3])
    quantity   = int(parts[4])
    product = db.get_product(product_id)
    balance = db.get_balance(query.from_user.id)
    total_price = product['price'] * quantity
    if product.get('requires_input'):
        # For link-required products we don't collect the link before payment.
        data = context.user_data['pending_purchase']
        data.update({
            'quantity': quantity,
            'user_input': None,
            'input_required': True,
        })
        # show confirmation and ask for confirmation
        await query.edit_message_text(
            f"📎 *ملاحظة مهمة:*\n"
            f"هذه الخدمة بتطلب الرابط بتاعك. بعد ما تضغط تأكيد، راح تديني الرابط مباشرة.\n\n"
            f"📦 المنتج: *{product['name']}*\n"
            f"🔢 الكمية: *{quantity}*\n"
            f"{format_price_summary(product['price'], quantity)}\n\n"
            f"💵 رصيدك: *${balance:.2f}*\n\n"
            f"هل تريد المتابعة والدفع ثم إرسال الرابط؟",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ نعم، تأكيد", callback_data=f"confirmbuy_{product_id}_{app_id}_{cat_id}_{quantity}"),
                 InlineKeyboardButton("❌ إلغاء", callback_data=f"app_{app_id}_{cat_id}")]
            ])
        )
        return

    await query.edit_message_text(
        f"✅ اخترت كمية *{quantity}*\n\n"
        f"📦 المنتج: *{product['name']}*\n"
        f"💰 السعر لكل وحدة: *${product['price']:.2f}*\n"
        f"🔢 الكمية: *{quantity}*\n"
        f"💵 الإجمالي: *${total_price:.2f}*\n"
        f"💼 رصيدك: *${balance:.2f}*\n\n"
        f"هل تريد تأكيد الشراء؟",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد", callback_data=f"confirmbuy_{product_id}_{app_id}_{cat_id}_{quantity}"),
             InlineKeyboardButton("❌ إلغاء", callback_data=f"app_{app_id}_{cat_id}")]
        ])
    )

async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts      = query.data.split("_")
    product_id = int(parts[1])
    app_id     = int(parts[2])
    cat_id     = int(parts[3])
    product = db.get_product(product_id)
    balance = db.get_balance(query.from_user.id)
    affordable_qty = int(balance // product['price'])
    max_qty = affordable_qty if product['stock'] < 0 else min(product['stock'], affordable_qty)
    context.user_data['pending_purchase'] = {
        'product_id': product_id,
        'app_id': app_id,
        'cat_id': cat_id,
        'max_qty': max_qty
    }
    context.user_data['state'] = WAITING_PURCHASE_QUANTITY
    available_text = "♾️ لا محدود" if (product.get('requires_input') or product['stock'] < 0) else str(product['stock'])
    await query.edit_message_text(
        f"📥 أدخل الكمية التي تريد شرائها:\n\n"
        f"📦 {product['name']}\n"
        f"💰 السعر لكل وحدة: *${product['price']:.2f}*\n"
        f"📊 المتوفر: *{available_text}*\n"
        f"💼 رصيدك: *${balance:.2f}*\n"
        f"_اكتب رقما بين 1 و {max_qty}_",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"app_{app_id}_{cat_id}")]])
    )

async def receive_purchase_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data.get('pending_purchase')
    if not data:
        await update.message.reply_text("❌ حدث خطأ، الرجاء إعادة المحاولة.")
        return
    try:
        quantity = int(update.message.text.strip())
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً أكبر من 0.")
        return
    max_qty = data.get('max_qty', 1)
    if quantity > max_qty:
        await update.message.reply_text(f"❌ الكمية غير متاحة. الحد الأقصى هو {max_qty}.")
        return
    product = db.get_product(data['product_id'])
    total_price = product['price'] * quantity
    balance = db.get_balance(update.effective_user.id)
    if product.get('requires_input'):
        data['quantity'] = quantity
        data['user_input'] = None
        data['input_required'] = True
        data['input_prompt'] = product.get('input_prompt') or 'أرسل الرابط أو الحساب المطلوب هنا:'
        context.user_data['pending_purchase_data'] = {
            'product_id': data['product_id'],
            'quantity': quantity,
            'app_id': data['app_id'],
            'cat_id': data['cat_id']
        }
        context.user_data['state'] = WAITING_PURCHASE_INPUT
        await update.message.reply_text(
            f"📎 *  , هذه الخدمة تطلب رابط أو حساب قبل إتمام الشراء .وبعد اختيار الكميه سيتم تأكيد الشراء تلقائي.*\n\n"
            f"📦 المنتج: *{product['name']}*\n"
            f"🔢 الكمية: *{quantity}*\n"
            f"{format_price_summary(product['price'], quantity)}\n\n"
            f"{data['input_prompt']}",
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text(
        f"✅ اخترت كمية *{quantity}*\n\n"
        f"📦 المنتج: *{product['name']}*\n"
        f"💰 السعر لكل وحدة: *${product['price']:.2f}*\n"
        f"🔢 الكمية: *{quantity}*\n"
        f"💵 الإجمالي: *${total_price:.2f}*\n"
        f"💼 رصيدك: *${balance:.2f}*\n\n"
        f"اضغط الزر لتأكيد الشراء:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تأكيد", callback_data=f"confirmbuy_{data['product_id']}_{data['app_id']}_{data['cat_id']}_{quantity}"),
             InlineKeyboardButton("❌ إلغاء", callback_data=f"app_{data['app_id']}_{data['cat_id']}")]
        ])
    )
    context.user_data.pop('state', None)

# ══════════════════════════════════════════════════════════
# WALLET
# ══════════════════════════════════════════════════════════

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance      = db.get_balance(user_id)
    transactions = db.get_transactions(user_id, limit=5)
    text = f"💼 *محفظتي*\n━━━━━━━━━━━━━━━━━━\n💰 الرصيد: *${balance:.2f}*\n\n📋 *آخر المعاملات:*\n"
    if transactions:
        for t in transactions:
            emoji = "➕" if t['type'] == 'deposit' else "🛒"
            sign  = "+" if t['type'] == 'deposit' else "-"
            text += f"{emoji} {sign}${abs(t['amount']):.2f} — {t['description']}\n"
    else:
        text += "_لا توجد معاملات بعد._"
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شحن رصيد",   callback_data="add_balance")],
        [InlineKeyboardButton("📋 كل الطلبات", callback_data="my_orders")],
        [InlineKeyboardButton("🔙 رجوع",        callback_data="main_menu")]
    ]))

async def show_wallet_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance      = db.get_balance(user_id)
    transactions = db.get_transactions(user_id, limit=5)
    text = f"💼 *محفظتي*\n━━━━━━━━━━━━━━━━━━\n💰 الرصيد: *${balance:.2f}*\n\n📋 *آخر المعاملات:*\n"
    if transactions:
        for t in transactions:
            emoji = "➕" if t['type'] == 'deposit' else "🛒"
            sign  = "+" if t['type'] == 'deposit' else "-"
            text += f"{emoji} {sign}${abs(t['amount']):.2f} — {t['description']}\n"
    else:
        text += "_لا توجد معاملات بعد._"
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شحن رصيد",   callback_data="add_balance")],
        [InlineKeyboardButton("📋 كل الطلبات", callback_data="my_orders")],
        [InlineKeyboardButton("🔙 رجوع",        callback_data="main_menu")]
    ]))

# ══════════════════════════════════════════════════════════
# ADD BALANCE
# ══════════════════════════════════════════════════════════

async def add_balance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = (
        "➕ *شحن الرصيد*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💳 *طرق الدفع المتاحة:*\n"
        "• Binance: `1199904304`\n"
        "• Vodafone Cash: `01028749936`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💵 *سعر التحويل:* 1 دولار = 55 جنيه مصري\n\n"
        "📌 *طريقة الشحن:*\n"
        "1- حوّل المبلغ المطلوب على أي وسيلة من وسائل الدفع\n"
        "2- بعد التحويل اكتب هنا المبلغ بالدولار الذي أرسلته\n\n"
        "📥 *مثال:*\n"
        "لو حولت 55 جنيه → اكتب: `1`\n"
        "لو حولت 110 جنيه → اكتب: `2`\n\n"
        "✍️ من فضلك أدخل المبلغ بالدولار الآن:"
    )

    await query.edit_message_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]
        ])
    )

    context.user_data['state'] = WAITING_PAYMENT_AMOUNT
    return WAITING_PAYMENT_AMOUNT

async def add_balance_start_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "➕ *شحن الرصيد*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "💳 *طرق الدفع المتاحة:*\n"
        "• Binance: `1199904304`\n"
        "• Vodafone Cash: `01028749936`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💵 *سعر التحويل:* 1 دولار = 55 جنيه مصري\n\n"
        "📌 *طريقة الشحن:*\n"
        "1- حوّل المبلغ المطلوب على أي وسيلة من وسائل الدفع\n"
        "2- بعد التحويل اكتب هنا المبلغ بالدولار الذي أرسلته\n\n"
        "📥 *مثال:*\n"
        "لو حولت 55 جنيه → اكتب: `1`\n"
        "لو حولت 110 جنيه → اكتب: `2`\n\n"
        "✍️ من فضلك أدخل المبلغ بالدولار الآن:"
    )

    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]
        ])
    )

    context.user_data['state'] = WAITING_PAYMENT_AMOUNT
    return WAITING_PAYMENT_AMOUNT

async def receive_purchase_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # two modes: after user sends link for post-purchase input, or attaching to existing order
    if context.user_data.get('state') != WAITING_PURCHASE_INPUT:
        return
    user_input = update.message.text.strip()
    if not user_input:
        await update.message.reply_text("❌ أرسل الرابط أو الحساب المطلوب.")
        return
    
    # if creating purchase now (user sent link after payment confirmation)
    pending_data = context.user_data.get('pending_purchase_data')
    if pending_data:
        product_id = pending_data['product_id']
        quantity = pending_data['quantity']
        user_id = update.effective_user.id
        product = db.get_product(product_id)
        
        # NOW purchase the product with the link
        success, result = db.purchase_product(user_id, product_id, quantity, user_input)
        context.user_data.pop('pending_purchase_data', None)
        context.user_data.pop('state', None)
        
        if success:
            # notify admin about the new order with link
            await notify_admin_order(context, update.effective_user, result['product_name'], quantity, user_input, price=product['price'] if product else None)
            await update.message.reply_text(
                f"✅ تم إرسال الرابط بنجاح!\n\n"
                f"🔢 رقم الطلب: #{result.get('purchase_id')}\n"
                f"📦 المنتج: *{result['product_name']}*\n"
                f"🔢 الكمية: *{quantity}*\n"
                f"💵 الرصيد المتبقي: *${result['new_balance']:.2f}*\n\n"
                f"سيتم معالجة طلبك من قبل الإدارة.",
                parse_mode='Markdown',
                reply_markup=main_menu_keyboard(user_id))
            return
        else:
            await update.message.reply_text(f"❌ فشل: {result}", parse_mode='Markdown')
            return
    
    # if adding input to existing order (from my_orders)
    pending_order = context.user_data.get('pending_input_order_id')
    if pending_order:
        try:
            db.set_order_user_input(pending_order, user_input)
            context.user_data.pop('pending_input_order_id', None)
            context.user_data.pop('state', None)
            await update.message.reply_text("✅ تم إرفاق الرابط/الحساب إلى طلبك.", parse_mode='Markdown')
            try:
                await notify_admin_order(context, update.effective_user, "(تحديث رابط/حساب)", 1, user_input)
            except:
                pass
            return
        except Exception as e:
            await update.message.reply_text(f"❌ فشل: {e}")
            return
    pending_purchase_input = context.user_data.get('pending_purchase_input_id')
    if pending_purchase_input:
        try:
            db.set_purchase_user_input(pending_purchase_input, user_input)
            context.user_data.pop('pending_purchase_input_id', None)
            context.user_data.pop('state', None)
            await update.message.reply_text("✅ تم إرفاق الرابط/الحساب إلى طلبك.", parse_mode='Markdown')
            try:
                await notify_admin_order(context, update.effective_user, "(تحديث رابط/حساب)", 1, user_input)
            except:
                pass
            return
        except Exception as e:
            await update.message.reply_text(f"❌ فشل: {e}")
            return
    
    await update.message.reply_text("❌ حدث خطأ، الرجاء إعادة المحاولة.")

async def receive_payment_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text.replace(',', '.'))
        if amount <= 0:
            raise ValueError
        context.user_data['deposit_amount'] = amount
        context.user_data['state'] = WAITING_PAYMENT_PROOF
        await update.message.reply_text(
            f"✅ المبلغ: *${amount:.2f}*\n\n"
            f"📸 *الخطوة 2:* أرسل *صورة* إيصال الدفع:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="main_menu")]]))
        return WAITING_PAYMENT_PROOF
    except ValueError:
        await update.message.reply_text("❌ أدخل مبلغاً صحيحاً (مثال: `25` أو `10.5`)", parse_mode='Markdown')
        return WAITING_PAYMENT_AMOUNT

async def receive_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("❌ أرسل *صورة* إيصال الدفع.", parse_mode='Markdown')
        return WAITING_PAYMENT_PROOF
    user   = update.effective_user
    photo  = update.message.photo[-1]
    amount = context.user_data.get('deposit_amount', 0)
    deposit_id = db.create_deposit_request(user.id, photo.file_id, amount)
    await update.message.reply_text(
        f"✅ *تم إرسال الطلب!*\n\n"
        f"🔢 رقم الطلب: `#{deposit_id}`\n"
        f"💰 المبلغ: *${amount:.2f}*\n"
        f"⏳ الحالة: *قيد المراجعة*\n\n"
        f"ستصلك رسالة فور الموافقة!",
        parse_mode='Markdown', reply_markup=main_menu_keyboard(user.id))
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id, photo=photo.file_id,
                caption=(
                    f"💳 *طلب إيداع جديد*\n━━━━━━━━━━━━━━━━━━\n"
                    f"👤 {user.first_name} (@{user.username or 'N/A'})\n"
                    f"🆔 `{user.id}`\n"
                    f"🔢 #{deposit_id}\n"
                    f"💰 *${amount:.2f}*"
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"✅ قبول ${amount:.2f}", callback_data=f"approve_deposit_{deposit_id}_{amount}"),
                     InlineKeyboardButton("❌ رفض",                callback_data=f"reject_deposit_{deposit_id}")]
                ]))
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")
    context.user_data.pop('state', None)
    context.user_data.pop('deposit_amount', None)
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════
# MY ORDERS
# ══════════════════════════════════════════════════════════

async def show_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    purchases = db.get_user_purchases(user_id)
    if not purchases:
        text = "📋 *طلباتي*\n\n_لم تقم بأي عمليات شراء بعد._"
    else:
        text = "📋 *طلباتي*\n━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for p in purchases:
            text += f"\n🛒 *{p['product_name']}* — ${p['total_price']:.2f}\n"
            text += f"   📅 {p['date']}\n"
            text += f"   📦 الكمية: *{p['quantity']}*\n"
            status_label = {
                'pending': 'قيد المعالجة',
                'in_progress': 'قيد التنفيذ',
                'completed': 'اكتملت',
                'failed': 'فشلت',
                'rejected': 'فشلت'
            }.get(p.get('status','pending'), p.get('status','pending'))
            text += f"   📊 الحالة: *{status_label}*"
            if p.get('speed_status') and p['speed_status'] != 'none':
                text += f" — *🚀 تم تقديم طلب تسريع*"
            text += "\n"
            if p.get('user_input'):
                text += f"   📎 الرابط/الحساب المرسل: `{p['user_input']}`\n"
            if p.get('speed_status') == 'none' and p.get('status') not in ['completed', 'failed', 'rejected']:
                keyboard.append([InlineKeyboardButton("🚀 طلب تسريع الخدمة", callback_data=f"request_speed_{p['id']}")])
            if p.get('requires_input') and not p.get('user_input'):
                keyboard.append([InlineKeyboardButton(f"أضف رابط/حساب لطلب #{p['id']}", callback_data=f"add_purchase_input_{p['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def show_orders_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    purchases = db.get_user_purchases(user_id)
    if not purchases:
        text = "📋 *طلباتي*\n\n_لم تقم بأي عمليات شراء بعد._"
    else:
        text = "📋 *طلباتي*\n━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for p in purchases:
            text += f"\n🛒 *{p['product_name']}* — ${p['total_price']:.2f}\n"
            text += f"   📅 {p['date']}\n"
            text += f"   📦 الكمية: *{p['quantity']}*\n"
            status_label = {
                'pending': 'قيد المعالجة',
                'in_progress': 'قيد التنفيذ',
                'completed': 'اكتملت',
                'failed': 'فشلت',
                'rejected': 'فشلت'
            }.get(p.get('status','pending'), p.get('status','pending'))
            text += f"   📊 الحالة: *{status_label}*"
            if p.get('speed_status') and p['speed_status'] != 'none':
                text += f" — *🚀 تم تقديم طلب تسريع*"
            text += "\n"
            if p.get('user_input'):
                text += f"   📎 الرابط/الحساب المرسل: `{p['user_input']}`\n"
            if p.get('speed_status') == 'none' and p.get('status') not in ['completed', 'failed', 'rejected']:
                keyboard.append([InlineKeyboardButton("🚀 طلب تسريع الخدمة", callback_data=f"request_speed_{p['id']}")])
            if p.get('requires_input') and not p.get('user_input'):
                keyboard.append([InlineKeyboardButton(f"أضف رابط/حساب لطلب #{p['id']}", callback_data=f"add_purchase_input_{p['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def request_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    purchase_id = int(query.data.split("_")[-1])
    purchase = db.get_purchase(purchase_id)
    if not purchase or purchase['user_id'] != query.from_user.id:
        await query.answer("الطلب غير موجود أو غير مسموح.", show_alert=True)
        return
    if purchase.get('speed_status') != 'none':
        await query.answer("تم تقديم طلب تسريع لهذا الطلب بالفعل.", show_alert=True)
        return
    if purchase.get('status') == 'completed':
        await query.answer("لا يمكن طلب تسريع لطلب مكتمل.", show_alert=True)
        return
    db.set_purchase_speed_status(purchase_id, 'pending')
    await notify_admin_speed_request(context, query.from_user, purchase_id, purchase.get('product_name'), purchase.get('quantity'))
    await query.edit_message_text(
        f"✅ تم تقديم طلب التسريع للطلب #{purchase_id}.\n"
        f"سيظهر للادمن لمتابعة الطلب فقط.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="my_orders")]])
    )

async def start_add_purchase_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    purchase_id = int(query.data.split("_")[-1])
    purchase = db.get_purchase(purchase_id)
    if not purchase or purchase['user_id'] != query.from_user.id:
        await query.answer("الطلب غير موجود أو غير مسموح.", show_alert=True)
        return
    context.user_data['pending_purchase_input_id'] = purchase_id
    context.user_data['state'] = WAITING_PURCHASE_INPUT
    await query.edit_message_text(
        "📎 أرسل الرابط أو الحساب المطلوب لهذا الطلب:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="my_orders")]])
    )

# ══════════════════════════════════════════════════════════
# HELP
# ══════════════════════════════════════════════════════════

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "ℹ️ *المساعدة والدعم*\n━━━━━━━━━━━━━━━━━━\n\n"
        "🛍️ *كيف تشتري:*\n1. اذهب للمنتجات\n2. اختر الكاتيجري ثم التطبيق\n3. اختر الخدمة وأكد الشراء\n\n"
        "💰 *كيف تشحن الرصيد:*\n1. اذهب لـ شحن رصيد\n2. أرسل الدفع\n3. ارفع الإيصال\n4. انتظر الموافقة\n\n"
        "📞 *تواصل مع الدعم:* `@MezoStoreeAdmin`",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))

async def show_help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ *المساعدة والدعم*\n━━━━━━━━━━━━━━━━━━\n\n"
        "🛍️ *كيف تشتري:*\n1. اذهب للمنتجات\n2. اختر الكاتيجري ثم التطبيق\n3. اختر الخدمة وأكد الشراء\n\n"
        "💰 *كيف تشحن الرصيد:*\n1. اذهب لـ شحن رصيد\n2. أرسل الدفع\n3. ارفع الإيصال\n4. انتظر الموافقة\n\n"
        "📞 *تواصل مع الدعم:* `@MezoStoreeAdmin`",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")]]))

# ══════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مسموح!", show_alert=True)
        return
    stats = db.get_stats()
    text = (
        f"⚙️ *لوحة الإدارة*\n━━━━━━━━━━━━━━━━━━\n"
        f"👥 المستخدمين: *{stats['users']}*\n"
        f"📂 الكاتيجريز: *{stats['categories']}*\n"
        f"📱 التطبيقات: *{stats['apps']}*\n"
        f"📦 المنتجات: *{stats['products']}*\n"
        f"🗃️ المخزون: *{stats['total_items']}*\n"
        f"🛒 الطلبات: *{stats['orders']}*\n"
        f"💰 الإيرادات: *${stats['revenue']:.2f}*\n"
        f"⏳ إيداعات معلقة: *{stats['pending_deposits']}*\n"
        f"🚀 تسريعات معلقة: *{stats.get('pending_speed_requests', 0)}*"
    )
    try:
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=admin_panel_keyboard())
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await admin_panel(update, context)

async def admin_speed_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    requests = db.get_speed_requests(limit=20, offset=0)
    if not requests:
        await query.edit_message_text(
            "🚀 *طلبات التسريع المعلقة*\n\n_لا توجد طلبات تسريع حالياً._",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]))
        return

    text = "🚀 *طلبات التسريع المعلقة*\n━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for r in requests:
        text += (
            f"\n🔢 #{r['id']} — *{r['product_name']}*\n"
            f"👤 {r.get('user_name') or 'N/A'} (@{r.get('username') or 'N/A'}) — 🆔 `{r['user_id']}`\n"
            f"🔢 الكمية: *{r.get('quantity')}*\n"
            f"📅 التاريخ: {r.get('date')}\n"
            f"📊 حالة الطلب: *{r.get('status','pending').upper()}*\n"
            f"🚀 الحالة: *تم تقديم طلب تسريع*\n"
        )
        keyboard.append([InlineKeyboardButton(f"🔎 تفاصيل #{r['id']}", callback_data=f"speed_request_detail_{r['id']}")])

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))



async def speed_request_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    purchase_id = int(query.data.split("_")[-1])
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    speed_status = purchase.get('speed_status', 'none')
    speed_label = {
        'pending': '🚀 تم تقديم طلب تسريع',
        'requested': '🚀 تم تقديم طلب تسريع',
        'approved': '🚀 تم تقديم طلب تسريع',
        'rejected': '🚀 تم تقديم طلب تسريع'
    }.get(speed_status, '')
    text = (
        f"🔎 *تفاصيل طلب التسريع #{purchase_id}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 المستخدم: {purchase.get('user_name')} (@{purchase.get('username') or 'N/A'}) — 🆔 `{purchase.get('user_id')}`\n"
        f"📦 الخدمة: *{purchase.get('product_name')}*\n"
        f"🔢 الكمية: *{purchase.get('quantity')}*\n"
        f"📅 التاريخ: {purchase.get('date')}\n"
        f"📎 الرابط/الحساب المرسل: `{purchase.get('user_input') or '_لم يرسل بعد_'}`\n"
        f"📊 حالة الطلب: *{purchase.get('status', 'pending').upper()}*\n"
        f"🚀 حالة التسريع: *{speed_label}*\n"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_speed_requests")]
    ])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)

# ══════════════════════════════════════════════════════════
# ADMIN — CATEGORIES MANAGEMENT
# ══════════════════════════════════════════════════════════

async def admin_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    cats = db.get_all_categories()
    keyboard = []
    text = f"📂 *إدارة الكاتيجريز* ({len(cats)})\n━━━━━━━━━━━━━━━━━━\n\n"
    for cat in cats:
        apps_count = len(db.get_apps_by_category(cat['id']))
        keyboard.append([InlineKeyboardButton(
            f"{cat['emoji']} {cat['name']} ({apps_count} تطبيق)",
            callback_data=f"admin_cat_{cat['id']}"
        )])
    keyboard.append([InlineKeyboardButton("➕ إضافة كاتيجري", callback_data="admin_add_category")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع",           callback_data="admin_panel")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_category_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    cat_id = int(query.data.split("_")[2])
    cat    = db.get_category(cat_id)
    apps   = db.get_apps_by_category(cat_id)
    keyboard = []
    text = (
        f"{cat['emoji']} *{cat['name']}*\n━━━━━━━━━━━━━━━━━━\n"
        f"التطبيقات: *{len(apps)}*\n\n"
    )
    for app in apps:
        products = db.get_products_by_app(app['id'])
        keyboard.append([InlineKeyboardButton(
            f"{app['emoji']} {app['name']} ({len(products)} خدمة)",
            callback_data=f"admin_app_{app['id']}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("➕ إضافة تطبيق",     callback_data=f"admin_add_app_{cat_id}")])
    keyboard.append([InlineKeyboardButton("🗑️ حذف الكاتيجري",  callback_data=f"admin_del_cat_{cat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع",             callback_data="admin_categories")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def start_add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    context.user_data['state'] = WAITING_CATEGORY_NAME
    await query.edit_message_text(
        "➕ *إضافة كاتيجري جديدة*\n\nأدخل *اسم الكاتيجري* (مثال: متابعين):",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="admin_categories")]]))

async def get_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_category_name'] = update.message.text.strip()
    context.user_data['state'] = WAITING_CATEGORY_EMOJI
    await update.message.reply_text(
        "أدخل *إيموجي* الكاتيجري (مثال: 👥 أو 👍 أو 👁️):\nأو اكتب `skip` لاستخدام 📁",
        parse_mode='Markdown')

async def get_category_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    emoji = "📁" if text.lower() == "skip" else text
    name  = context.user_data.get('new_category_name', 'بدون اسم')
    cat_id = db.add_category(name, emoji)
    context.user_data.pop('state', None)
    await update.message.reply_text(
        f"✅ *تم إنشاء الكاتيجري!*\n\n{emoji} *{name}*\n\nالآن أضف تطبيقات لها.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"➕ إضافة تطبيق لـ {name}", callback_data=f"admin_add_app_{cat_id}")],
            [InlineKeyboardButton("🔙 إدارة الكاتيجريز",       callback_data="admin_categories")]
        ]))

async def admin_delete_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    cat_id = int(query.data.split("_")[3])
    db.delete_category(cat_id)
    await query.answer("✅ تم الحذف!", show_alert=True)
    query.data = "admin_categories"
    await admin_categories(update, context)

# ══════════════════════════════════════════════════════════
# ADMIN — APPS MANAGEMENT
# ══════════════════════════════════════════════════════════

async def admin_app_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts  = query.data.split("_")
    app_id = int(parts[2])
    cat_id = int(parts[3])
    app      = db.get_app(app_id)
    products = db.get_products_by_app(app_id)
    keyboard = []
    text = (
        f"{app['emoji']} *{app['name']}*\n━━━━━━━━━━━━━━━━━━\n"
        f"الخدمات: *{len(products)}*\n\n"
    )
    for p in products:
        emoji = "🟢" if p['stock'] > 0 else "🔴"
        keyboard.append([InlineKeyboardButton(
            f"{emoji} {p['name']} (${p['price']:.2f}) — {p['stock']} قطعة",
            callback_data=f"admin_prod_{p['id']}_{app_id}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("➕ إضافة خدمة",      callback_data=f"admin_add_prod_{app_id}_{cat_id}")])
    keyboard.append([InlineKeyboardButton("🗑️ حذف التطبيق",    callback_data=f"admin_del_app_{app_id}_{cat_id}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع",             callback_data=f"admin_cat_{cat_id}")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def start_add_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_id = int(query.data.split("_")[3])
    context.user_data.clear()
    context.user_data['adding_app_to_cat'] = cat_id
    context.user_data['state'] = WAITING_APP_NAME
    cat = db.get_category(cat_id)
    await query.edit_message_text(
        f"➕ *إضافة تطبيق إلى: {cat['name']}*\n\nأدخل *اسم التطبيق* (مثال: Instagram):",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_cat_{cat_id}")]]))

async def get_app_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_app_name'] = update.message.text.strip()
    context.user_data['state'] = WAITING_APP_EMOJI
    await update.message.reply_text(
        "أدخل *إيموجي* التطبيق (مثال: 📸 أو 👍 أو 🎵):\nأو اكتب `skip` لاستخدام 📱",
        parse_mode='Markdown')

async def get_app_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text   = update.message.text.strip()
    emoji  = "📱" if text.lower() == "skip" else text
    name   = context.user_data.get('new_app_name', 'بدون اسم')
    cat_id = context.user_data.get('adding_app_to_cat')
    app_id = db.add_app(cat_id, name, emoji)
    context.user_data.pop('state', None)
    await update.message.reply_text(
        f"✅ *تم إنشاء التطبيق!*\n\n{emoji} *{name}*\n\nالآن أضف خدمات له.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"➕ إضافة خدمة لـ {name}", callback_data=f"admin_add_prod_{app_id}_{cat_id}")],
            [InlineKeyboardButton("🔙 رجوع للتطبيق",           callback_data=f"admin_cat_{cat_id}")]
        ]))

async def admin_delete_app(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts  = query.data.split("_")
    app_id = int(parts[3])
    cat_id = int(parts[4])
    db.delete_app(app_id)
    await query.answer("✅ تم الحذف!", show_alert=True)
    query.data = f"admin_cat_{cat_id}"
    await admin_category_detail(update, context)

async def start_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts  = query.data.split("_")
    app_id = int(parts[3])
    cat_id = int(parts[4])
    context.user_data.clear()
    context.user_data['new_product']         = {}
    context.user_data['new_product_app_id']  = app_id
    context.user_data['new_product_cat_id']  = cat_id
    context.user_data['state']               = WAITING_PRODUCT_NAME
    app = db.get_app(app_id)
    await query.edit_message_text(
        f"➕ *إضافة خدمة إلى: {app['name']}*\n\nالخطوة 1/3: أدخل *اسم الخدمة*:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_app_{app_id}_{cat_id}")]]))

async def get_product_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_product']['name'] = update.message.text
    context.user_data['state'] = WAITING_PRODUCT_DESC
    await update.message.reply_text("الخطوة 2/3: أدخل *الوصف*:", parse_mode='Markdown')

async def get_product_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['new_product']['description'] = update.message.text
    context.user_data['state'] = WAITING_PRODUCT_PRICE
    await update.message.reply_text("الخطوة 3/3: أدخل *السعر* (مثال: 9.99):", parse_mode='Markdown')

async def get_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price  = float(update.message.text)
        context.user_data['new_product']['price'] = price
        context.user_data['state'] = WAITING_PRODUCT_TYPE
        await update.message.reply_text(
            "الخطوة 4/4: اختر نوع الخدمة التالية:\n"
            "1. يرسل المستخدم رابط/حساب\n"
            "2. نقدم له حساب/رابط جاهز من الإدارة\n"
            "3. خدمة لانهائية بدون مخزون\n\n"
            "اختر الطريقة المناسبة من الأزرار أدناه.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("يرسل المستخدم رابط/حساب", callback_data="admin_set_product_type_input")],
                    [InlineKeyboardButton("أرسل له حساب/رابط جاهز", callback_data="admin_set_product_type_ready")]
                ])
        )
    except ValueError:
        await update.message.reply_text("❌ أدخل رقماً صحيحاً (مثال: 9.99)")

async def set_product_type_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['new_product_type'] = 'input'
    context.user_data['new_product_infinite'] = 1
    app_id = context.user_data.get('new_product_app_id')
    cat_id = context.user_data.get('new_product_cat_id')
    # go directly to input prompt; link-required services are treated as infinite
    context.user_data['state'] = WAITING_PRODUCT_INPUT_PROMPT
    await query.edit_message_text(
        "الخطوة 5/5: اكتب رسالة الطلب الإضافية التي يحتاجها المستخدم بعد الشراء.\n" 
        "اكتب `skip` لاستخدام النص الافتراضي (سيتم ضبطه إلى 'أرسل الرابط').",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_app_{app_id}_{cat_id}")]])
    )

async def set_product_type_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data['new_product_type'] = 'ready'
    app_id = context.user_data.get('new_product_app_id')
    cat_id = context.user_data.get('new_product_cat_id')
    await query.edit_message_text(
        "هل تريد أن تكون هذه الخدمة *لانهائية* (بدون مخزون)؟",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("نعم - لانهائية", callback_data="admin_set_product_infinite_yes")],
            [InlineKeyboardButton("لا", callback_data="admin_set_product_infinite_no")]
        ])
    )

async def handle_product_infinite_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    choice = query.data.split("_")[-1]  # yes or no
    infinite = 1 if choice == 'yes' else 0
    product = context.user_data.get('new_product')
    product_type = context.user_data.get('new_product_type')
    app_id = context.user_data.get('new_product_app_id')
    cat_id = context.user_data.get('new_product_cat_id')
    if not product or not product_type:
        await query.answer("حدث خطأ، أعد المحاولة.", show_alert=True)
        return
    if product_type == 'input':
        # save infinite flag and ask for input prompt
        context.user_data['new_product_infinite'] = infinite
        context.user_data['state'] = WAITING_PRODUCT_INPUT_PROMPT
        await query.edit_message_text(
            "الخطوة 5/5: اكتب رسالة الطلب الإضافية التي يحتاجها المستخدم بعد الشراء.\n"
            "مثال: أرسل الرابط أو الحساب.\n"
            "اكتب `skip` إذا أردت استخدام النص الافتراضي.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_app_{app_id}_{cat_id}")]])
        )
        return

    # product_type == 'ready': create product now with infinite flag
    product_id = db.add_product(
        product['name'],
        product['description'],
        product['price'],
        app_id,
        0,
        '',
        infinite
    )
    context.user_data['adding_item_to']     = product_id
    context.user_data['adding_item_app_id'] = app_id
    context.user_data['adding_item_cat_id'] = cat_id
    context.user_data['state']              = WAITING_ITEM_CONTENT
    created_text = f"✅ *تم إنشاء الخدمة: {product['name']}*\n\n"
    if infinite:
        created_text += "هذه الخدمة لانهائية بدون مخزون.\n"
    created_text += "هذه الخدمة ترسل حساب/رابط جاهز من الإدارة بعد الشراء.\n"
    created_text += "أضف العناصر واحداً تلو الآخر أو اضغط انتهيت عند الانتهاء."
    await query.edit_message_text(
        created_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ انتهيت", callback_data=f"admin_prod_{product_id}_{app_id}_{cat_id}")]
        ])
    )

async def get_product_input_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    product = context.user_data.get('new_product')
    app_id = context.user_data.get('new_product_app_id')
    cat_id = context.user_data.get('new_product_cat_id')
    product_type = context.user_data.get('new_product_type')
    if not product or product_type != 'input':
        await update.message.reply_text("❌ حدث خطأ، أعد المحاولة.")
        return
    prompt = text if text.lower() != 'skip' else 'أرسل الرابط أو الحساب المطلوب هنا:'
    product_id = db.add_product(
        product['name'],
        product['description'],
        product['price'],
        app_id,
        1,
        'أرسل الرابط',
        1
    )
    context.user_data.pop('state', None)
    context.user_data.pop('new_product_type', None)
    await update.message.reply_text(
        f"✅ *تم إنشاء الخدمة: {product['name']}*\n\n"
        "هذه الخدمة تطلب رابط/حساب من المستخدم بعد الشراء، وستتم معالجة الطلب بواسطة الإدارة.",
        parse_mode='Markdown'
    )

async def start_add_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    product_id = int(parts[2])
    app_id     = int(parts[3])
    cat_id     = int(parts[4])
    product = db.get_product(product_id)
    context.user_data.clear()
    context.user_data['adding_item_to']     = product_id
    context.user_data['adding_item_app_id'] = app_id
    context.user_data['adding_item_cat_id'] = cat_id
    context.user_data['state']              = WAITING_ITEM_CONTENT
    await query.edit_message_text(
        f"➕ *إضافة عنصر إلى: {product['name']}*\n\n"
        f"أرسل المحتوى (تفاصيل الحساب، مفتاح الترخيص، إلخ)\n\n"
        f"يمكنك إرسال *عدة عناصر* — أرسل كل واحد كرسالة منفصلة.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ انتهيت", callback_data=f"admin_prod_{product_id}_{app_id}_{cat_id}")],
            [InlineKeyboardButton("❌ إلغاء",  callback_data=f"admin_prod_{product_id}_{app_id}_{cat_id}")]
        ]))

async def start_add_order_input(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id=None):
    query = update.callback_query
    # order_id may be passed directly or via callback data
    if order_id is None:
        parts = query.data.split("_")
        order_id = int(parts[-1])
    await query.answer()
    context.user_data['pending_input_order_id'] = order_id
    context.user_data['state'] = WAITING_PURCHASE_INPUT
    await query.edit_message_text(
        "أرسل الرابط",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="my_orders")]])
    )

async def receive_item_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') != WAITING_ITEM_CONTENT:
        return
    product_id = context.user_data.get('adding_item_to')
    if not product_id:
        return
    content = update.message.text.strip()
    if not content:
        return
    db.add_item_to_product(product_id, content)
    product = db.get_product(product_id)
    await update.message.reply_text(
        f"✅ *تم إضافة العنصر!*\n\n"
        f"📦 الخدمة: *{product['name']}*\n"
        f"🗃️ المخزون الحالي: *{product['stock']}*\n\n"
        f"أرسل عنصراً آخر أو اضغط *انتهيت*.",
        parse_mode='Markdown')

async def manage_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    product_id = int(parts[2])
    app_id     = int(parts[3])
    cat_id     = int(parts[4])
    product = db.get_product(product_id)
    items   = db.get_product_items(product_id)
    if not items:
        await query.edit_message_text(
            f"📦 *{product['name']}*\n\nلا يوجد مخزون.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة عنصر", callback_data=f"admin_additem_{product_id}_{app_id}_{cat_id}")],
                [InlineKeyboardButton("🔙 رجوع",        callback_data=f"admin_prod_{product_id}_{app_id}_{cat_id}")]
            ]))
        return
    keyboard = []
    text = f"🗑️ *حذف عناصر من: {product['name']}*\n━━━━━━━━━━━━━━━━━━\n\n"
    for item in items[:10]:
        preview = item['content'][:25] + "..." if len(item['content']) > 25 else item['content']
        text += f"ID {item['id']}: `{preview}`\n"
        keyboard.append([InlineKeyboardButton(
            f"🗑️ حذف ID {item['id']}",
            callback_data=f"admin_delitem_{item['id']}_{product_id}_{app_id}_{cat_id}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_prod_{product_id}_{app_id}_{cat_id}")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def delete_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    item_id    = int(parts[2])
    product_id = int(parts[3])
    app_id     = int(parts[4])
    cat_id     = int(parts[5])
    db.delete_item(item_id)
    await query.answer("✅ تم الحذف!", show_alert=True)
    query.data = f"admin_mgitems_{product_id}_{app_id}_{cat_id}"
    await manage_items(update, context)


async def admin_product_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    product_id = int(parts[2])
    app_id     = int(parts[3])
    cat_id     = int(parts[4])
    product = db.get_product(product_id)
    if not product:
        await query.answer("غير موجود!", show_alert=True)
        return
    items = db.get_product_items(product_id)
    text  = (
        f"📦 *{product['name']}*\n━━━━━━━━━━━━━━━━━━\n"
        f"📝 {product['description']}\n"
        f"💰 السعر: ${product['price']:.2f}\n"
        f"🗃️ المخزون: *{product['stock']}*\n\n"
    )
    if product.get('requires_input'):
        text += "📎 هذه الخدمة تطلب من المستخدم إرسال رابط/حساب قبل إتمام الشراء.\n"
        if product.get('input_prompt'):
            text += f"📌 {product['input_prompt']}\n"
        text += "\n"
    else:
        text += "✅ هذه الخدمة تُرسل حساب/محتوى جاهز من الإدارة بعد الشراء.\n\n"
    if items:
        text += "📋 *العناصر المتاحة:*\n"
        for i, item in enumerate(items[:5], 1):
            preview = item['content'][:30] + "..." if len(item['content']) > 30 else item['content']
            text += f"{i}. `{preview}`\n"
        if len(items) > 5:
            text += f"_... و {len(items)-5} أكثر_\n"
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عنصر",    callback_data=f"admin_additem_{product_id}_{app_id}_{cat_id}"),
         InlineKeyboardButton("🗑️ حذف عناصر",    callback_data=f"admin_mgitems_{product_id}_{app_id}_{cat_id}")],
        [InlineKeyboardButton("🗑️ حذف الخدمة",   callback_data=f"admin_delprod_{product_id}_{app_id}_{cat_id}")],
        [InlineKeyboardButton("🔙 رجوع",           callback_data=f"admin_app_{app_id}_{cat_id}")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    query.data = f"admin_mgitems_{product_id}_{app_id}_{cat_id}"
    await manage_items(update, context)

async def delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    product_id = int(parts[2])
    app_id     = int(parts[3])
    cat_id     = int(parts[4])
    db.delete_product(product_id)
    await query.answer("✅ تم الحذف!", show_alert=True)
    query.data = f"admin_app_{app_id}_{cat_id}"
    await admin_app_detail(update, context)

# ══════════════════════════════════════════════════════════
# ADMIN — ALL PRODUCTS VIEW (flat list)
# ══════════════════════════════════════════════════════════

async def admin_products_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    products = db.get_all_products()
    text = f"📦 *كل الخدمات ({len(products)})*\n━━━━━━━━━━━━━━━━━━\n\n"
    for p in products:
        emoji = "🟢" if p['stock'] > 0 else "🔴"
        text += f"{emoji} *{p['name']}* — ${p['price']:.2f} ({p['stock']} قطعة)\n"
    await query.edit_message_text(text, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]))

# ══════════════════════════════════════════════════════════
# ADMIN — DEPOSITS
# ══════════════════════════════════════════════════════════

async def admin_deposits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deposits = db.get_pending_deposits()
    if not deposits:
        await query.edit_message_text(
            "💳 *الإيداعات المعلقة*\n\n✅ لا توجد طلبات معلقة!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]]))
        return
    keyboard = []
    text = f"💳 *الإيداعات المعلقة ({len(deposits)})*\n━━━━━━━━━━━━━━━━━━\n\n"
    for dep in deposits:
        text += f"🔢 #{dep['id']} — 👤 {dep['username']} — ${dep['amount']:.2f}\n"
        keyboard.append([InlineKeyboardButton(f"👁️ مراجعة #{dep['id']}", callback_data=f"review_deposit_{dep['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def review_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deposit_id = int(query.data.split("_")[2])
    deposit    = db.get_deposit(deposit_id)
    if not deposit:
        await query.answer("غير موجود!", show_alert=True)
        return
    amount = deposit['amount']
    await context.bot.send_photo(
        chat_id=query.from_user.id,
        photo=deposit['photo_file_id'],
        caption=(
            f"💳 *إيداع #{deposit_id}*\n"
            f"👤 {deposit['username']}\n"
            f"🆔 `{deposit['user_id']}`\n"
            f"💵 المبلغ: *${amount}*\n\nهل تقبل هذا الإيداع؟"
        ),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ قبول",  callback_data=f"approve_deposit_{deposit_id}_{amount}")],
            [InlineKeyboardButton("❌ رفض",   callback_data=f"reject_deposit_{deposit_id}")]
        ]))

async def approve_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts      = query.data.split("_")
    deposit_id = int(parts[2])
    if len(parts) < 4:
        context.user_data['pending_deposit_id'] = deposit_id
        context.user_data['state'] = WAITING_ADD_BALANCE_AMOUNT
        await query.message.reply_text("أدخل المبلغ المراد إضافته:")
        return
    amount  = float(parts[3])
    deposit = db.get_deposit(deposit_id)
    if not deposit:
        return
    db.approve_deposit(deposit_id, amount, query.from_user.id)
    new_balance = db.get_balance(deposit['user_id'])
    try:
        await context.bot.send_message(
            chat_id=deposit['user_id'],
            text=f"✅ *تم إضافة ${amount:.2f} لرصيدك!*\n💼 الرصيد الجديد: *${new_balance:.2f}*\n\nيمكنك التسوق الآن! 🛍️",
            parse_mode='Markdown', reply_markup=main_menu_keyboard(deposit['user_id']))
    except:
        pass
    try:
        await query.edit_message_caption(
            caption=f"✅ تم قبول إيداع #{deposit_id} — ${amount:.2f} أضيفت لـ {deposit['username']}",
            parse_mode='Markdown')
    except:
        pass

async def reject_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deposit_id = int(query.data.split("_")[2])
    deposit    = db.get_deposit(deposit_id)
    if not deposit:
        return
    db.reject_deposit(deposit_id, query.from_user.id)
    try:
        await context.bot.send_message(
            chat_id=deposit['user_id'],
            text=f"❌ *تم رفض طلب الإيداع #{deposit_id}*\n\nتواصل مع الدعم إذا كان هناك خطأ.",
            parse_mode='Markdown', reply_markup=main_menu_keyboard(deposit['user_id']))
    except:
        pass
    try:
        await query.edit_message_caption(caption=f"❌ تم رفض إيداع #{deposit_id}", parse_mode='Markdown')
    except:
        await query.edit_message_text(f"❌ تم رفض إيداع #{deposit_id}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_deposits")]]))

# ══════════════════════════════════════════════════════════
async def receive_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("state") != WAITING_BROADCAST_MESSAGE:
        return

    message = update.message.text
    users = db.get_all_users()

    sent = 0
    failed = 0

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["id"],
                text=message
            )
            sent += 1
        except:
            failed += 1

    context.user_data.pop("state", None)

    await update.message.reply_text(
        f"✅ تم الإرسال لـ {sent} مستخدم\n❌ فشل: {failed}",
        reply_markup=admin_panel_keyboard()
    )
    

async def complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    purchase_id = int(parts[2])
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    if purchase.get('status') == 'completed':
        await query.answer("الطلب بالفعل مكتمل.", show_alert=True)
        return
    # set purchase and related orders to completed
    db.set_purchase_status(purchase_id, 'completed')
    db.set_orders_status_by_purchase(purchase_id, 'completed')
    # notify user with delivered items
    try:
        notify_text = (
            f"✅ تم إتمام طلبك بنجاح!\n"
            f"📦 الخدمة: *{purchase.get('product_name')}*\n"
            f"🔢 الكمية: *{purchase.get('quantity')}*\n"
            f"📎 الرابط/الحساب الذي أرسلته: `{purchase.get('user_input') or '_لا يوجد_'}`"
        )
        await context.bot.send_message(chat_id=purchase['user_id'], text=notify_text, parse_mode='Markdown')
    except Exception:
        pass
    await query.answer("تم وسم الطلب كمكتمل.", show_alert=True)
    # refresh admin orders page 1
    query.data = "admin_orders_1"
    await admin_orders(update, context)


async def reject_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    purchase_id = int(parts[2])
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    await query.edit_message_text(
        f"❌ اختر سبب رفض طلب #{purchase_id}:\n\n"
        "يرجى اختيار السبب المناسب حتى يتلقى المستخدم رسالة دقيقة.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("الرابط غير صحيح", callback_data=f"reject_purchase_reason_wrong_{purchase_id}")],
            [InlineKeyboardButton("الخدمة معطلة", callback_data=f"reject_purchase_reason_down_{purchase_id}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_orders_1")]
        ])
    )


async def execute_reject_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    reason = parts[3]
    purchase_id = int(parts[4])
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    success, err = db.refund_purchase(purchase_id)
    if not success:
        await query.answer(f"فشل الاسترجاع: {err}", show_alert=True)
        return
    user_message = (
        f"❌ تم رفض طلبك #{purchase_id}.\n"
        f"📦 الخدمة: *{purchase.get('product_name')}*\n"
        f"💰 المبلغ المُسترجَع: *${purchase.get('total_price'):.2f}*\n\n"
    )
    if reason == 'wrong':
        user_message += "السبب: الرابط الذي أرسلته غير صحيح."
    else:
        user_message += "السبب: الخدمة معطلة حالياً."
    try:
        await context.bot.send_message(chat_id=purchase['user_id'], text=user_message, parse_mode='Markdown')
    except:
        pass
    await query.answer("تم رفض الطلب واسترجاع المبلغ.", show_alert=True)
    query.data = "admin_orders_1"
    await admin_orders(update, context)


async def admin_set_purchase_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.answer("تنسيق غير صالح.", show_alert=True)
        return
    status = parts[3]
    purchase_id = int(parts[4]) if len(parts) > 4 else None
    if not purchase_id:
        await query.answer("الطلب غير موجود.", show_alert=True)
        return
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    valid_status = {
        'pending': 'قيد المعالجة',
        'in_progress': 'قيد التنفيذ',
        'completed': 'اكتملت',
        'failed': 'فشلت'
    }
    if status not in valid_status:
        await query.answer("الحالة غير مدعومة.", show_alert=True)
        return
    if purchase.get('status') == status:
        await query.answer(f"الحالة بالفعل {valid_status[status]}.", show_alert=True)
        return
    db.set_purchase_status(purchase_id, status)
    if status in ['completed', 'failed']:
        db.set_orders_status_by_purchase(purchase_id, status)
    user_message = None
    if status == 'pending':
        user_message = "✅ تم تحديث حالة طلبك إلى *قيد المعالجة*."
    elif status == 'in_progress':
        user_message = "✅ طلبك الآن *قيد التنفيذ* من قِبل الإدارة."
    elif status == 'completed':
        user_message = (
            f"✅ تم إتمام طلبك #{purchase_id} بنجاح!\n"
            f"📦 الخدمة: *{purchase.get('product_name')}*\n"
            f"🔢 الكمية: *{purchase.get('quantity')}*"
        )
    elif status == 'failed':
        user_message = (
            f"❌ تم تحديث حالة طلبك #{purchase_id} إلى *فشلت*.")
    if user_message:
        try:
            await context.bot.send_message(
                chat_id=purchase['user_id'],
                text=user_message,
                parse_mode='Markdown'
            )
        except Exception:
            pass
    await query.answer(f"تم تغيير حالة الطلب إلى {valid_status[status]}.", show_alert=True)
    query.data = f"order_detail_{purchase_id}"
    await order_detail(update, context)


async def order_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    purchase_id = int(parts[2])
    purchase = db.get_purchase(purchase_id)
    if not purchase:
        await query.answer("الطلب غير موجود!", show_alert=True)
        return
    speed_status = purchase.get('speed_status', 'none')
    speed_label = ''
    if speed_status != 'none':
        speed_label = {
            'pending': '🚀 طلب تسريع معلق',
            'approved': '🚀 التسريع موافق عليه',
            'rejected': '🚀 تم رفض طلب التسريع'
        }.get(speed_status, speed_status)
    text = (
        f"🔎 *تفاصيل الطلب #{purchase_id}*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 المستخدم: {purchase.get('user_name')} (@{purchase.get('username') or 'N/A'}) — 🆔 `{purchase.get('user_id')}`\n"
        f"📦 الخدمة: *{purchase.get('category_name')} › {purchase.get('app_name')} › {purchase.get('product_name')}*\n"
        f"🔢 الكمية المطلوبة: *{purchase.get('quantity')}*\n"
        f"💰 الإجمالي: *${purchase.get('total_price'):.2f}*\n"
        f"📅 التاريخ: {purchase.get('date')}\n"
        f"📎 الرابط/الحساب المرسل:\n`{purchase.get('user_input') or '_لم يرسل بعد_'}`\n"
        f"📊 الحالة: *{purchase.get('status', 'pending').upper()}*\n"
    )
    # append speed label separately to avoid backslash inside f-string expression
    if speed_label:
        text += f"🚀 {speed_label}\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_orders_1")]])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=kb)
# ADMIN — USERS
# ══════════════════════════════════════════════════════════

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    users = db.get_all_users()
    text  = f"👥 *كل المستخدمين ({len(users)})*\n━━━━━━━━━━━━━━━━━━\n\n"
    keyboard = []
    for user in users[:20]:
        text += f"👤 {user['name']} — 💰 ${user['balance']:.2f}\n"
        keyboard.append([InlineKeyboardButton(f"{user['name']} — ${user['balance']:.2f}", callback_data=f"admin_view_user_{user['id']}")])
    if len(users) > 20:
        text += f"\n_... و {len(users)-20} أكثر_"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_view_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    if len(parts) < 4:
        await query.answer("المستخدم غير موجود!", show_alert=True)
        return
    user_id = int(parts[3])
    user = db.get_user(user_id)
    if not user:
        await query.answer("المستخدم غير موجود!", show_alert=True)
        return
    text = (
        f"👤 *بيانات المستخدم*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"اسم: *{user['name']}*\n"
        f"معرّف: `{user['id']}`\n"
        f"اسم المستخدم: @{user['username'] or 'N/A'}\n"
        f"💰 الرصيد: *${user['balance']:.2f}*\n"
        f"📅 أنشئ في: {user['created_at']}\n"
    )
    keyboard = [
        [InlineKeyboardButton("🧹 صفّر الرصيد", callback_data=f"admin_reset_user_balance_{user_id}"),
         InlineKeyboardButton("✏️ عدّل الرصيد", callback_data=f"admin_edit_user_balance_{user_id}")],
        [InlineKeyboardButton("🗑️ احذف المستخدم", callback_data=f"admin_delete_user_{user_id}" )],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]
    ]
    await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_reset_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.split("_")[4])
    user = db.get_user(user_id)
    if not user:
        await query.answer("المستخدم غير موجود!", show_alert=True)
        return
    db.set_user_balance(user_id, 0)
    await query.edit_message_text(
        f"✅ تم تصفير رصيد المستخدم *{user['name']}*\n"
        f"الرصيد الآن: *$0.00*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_view_user_{user_id}")]])
    )

async def admin_edit_user_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.split("_")[4])
    user = db.get_user(user_id)
    if not user:
        await query.answer("المستخدم غير موجود!", show_alert=True)
        return
    context.user_data['pending_admin_balance_user'] = user_id
    context.user_data['state'] = WAITING_ADMIN_BALANCE_EDIT
    await query.edit_message_text(
        f"✏️ أدخل الرصيد الجديد للمستخدم *{user['name']}* (حاليًا ${user['balance']:.2f}):",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data=f"admin_view_user_{user_id}")]])
    )

async def admin_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.split("_")[3])
    user = db.get_user(user_id)
    if not user:
        await query.answer("المستخدم غير موجود!", show_alert=True)
        return
    db.delete_user(user_id)
    await query.edit_message_text(
        f"✅ تم حذف المستخدم *{user['name']}* وجميع بياناته.",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]])
    )

# ══════════════════════════════════════════════════════════
async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    # نحفظ الحالة
    context.user_data["state"] = WAITING_BROADCAST_MESSAGE

    await query.edit_message_text(
        "📢 اكتب الرسالة التي تريد إرسالها لكل المستخدمين:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_panel")]
        ])
    )


    
# HANDLE TEXT (state machine)

# ══════════════════════════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check for main menu button presses first
    text = update.message.text.strip()
    if text in ["🛍️ المنتجات", "💼 محفظتي", "➕ شحن رصيد", "📋 طلباتي", "ℹ️ مساعدة"]:
        await handle_main_menu_button(update, context)
        return
    
    state = context.user_data.get('state')

    if state == WAITING_CATEGORY_NAME:
        await get_category_name(update, context)
    elif state == WAITING_CATEGORY_EMOJI:
        await get_category_emoji(update, context)
    elif state == WAITING_APP_NAME:
        await get_app_name(update, context)
    elif state == WAITING_APP_EMOJI:
        await get_app_emoji(update, context)
    elif state == WAITING_PRODUCT_NAME:
        await get_product_name(update, context)
    elif state == WAITING_PRODUCT_DESC:
        await get_product_desc(update, context)
    elif state == WAITING_PRODUCT_PRICE:
        await get_product_price(update, context)
    elif state == WAITING_PRODUCT_INPUT_PROMPT:
        await get_product_input_prompt(update, context)
    elif state == WAITING_ITEM_CONTENT:
        await receive_item_content(update, context)
    elif state == WAITING_PAYMENT_AMOUNT:
        await receive_payment_amount(update, context)
    elif state == WAITING_PURCHASE_QUANTITY:
        await receive_purchase_quantity(update, context)
    elif state == WAITING_PURCHASE_INPUT:
        await receive_purchase_input(update, context)
    elif state == WAITING_BROADCAST_MESSAGE:
        await receive_broadcast_message(update, context)
    elif state == WAITING_PAYMENT_PROOF:
        await update.message.reply_text("📸 أرسل *صورة* الإيصال.", parse_mode='Markdown')
    elif state == WAITING_ADMIN_BALANCE_EDIT:
        try:
            new_balance = float(update.message.text.replace(',', '.'))
            user_id = context.user_data.get('pending_admin_balance_user')
            if user_id is None:
                await update.message.reply_text("❌ حدث خطأ، الرجاء إعادة المحاولة.")
                return
            db.set_user_balance(user_id, new_balance)
            context.user_data.pop('state', None)
            context.user_data.pop('pending_admin_balance_user', None)
            await update.message.reply_text(
                f"✅ تم تحديث رصيد المستخدم إلى ${new_balance:.2f}.",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ أدخل رقماً صحيحاً للمبلغ.")
    elif state == WAITING_ADD_BALANCE_AMOUNT:
        try:
            amount     = float(update.message.text)
            deposit_id = context.user_data.get('pending_deposit_id')
            if deposit_id:
                deposit = db.get_deposit(deposit_id)
                db.approve_deposit(deposit_id, amount, update.effective_user.id)
                new_balance = db.get_balance(deposit['user_id'])
                try:
                    await context.bot.send_message(
                        chat_id=deposit['user_id'],
                        text=f"✅ *تم إضافة ${amount:.2f}!*\n💼 الرصيد: *${new_balance:.2f}*",
                        parse_mode='Markdown',
                        reply_markup=main_menu_keyboard(deposit['user_id']))
                except:
                    pass
                await update.message.reply_text(
                    f"✅ تم قبول إيداع #{deposit_id}! أضيف ${amount:.2f}",
                    reply_markup=admin_panel_keyboard())
                context.user_data.pop('state', None)
                context.user_data.pop('pending_deposit_id', None)
        except ValueError:
            await update.message.reply_text("❌ أدخل رقماً صحيحاً")
            
            

# ══════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data  = query.data

    # clear item-adding state when navigating away
    if context.user_data.get('state') == WAITING_ITEM_CONTENT:
        if not (data.startswith("admin_prod_") or data.startswith("admin_additem_")):
            context.user_data.pop('state', None)
            context.user_data.pop('adding_item_to', None)

    # deposit actions first
    if data.startswith("approve_deposit_"):
        await approve_deposit(update, context); return
    if data.startswith("reject_deposit_"):
        await reject_deposit(update, context);  return
    if data.startswith("review_deposit_"):
        await review_deposit(update, context);  return
    

    # simple routes
    routes = {
        "main_menu":          start,
        "categories":         show_categories,
        "wallet":             show_wallet,
        "add_balance":        add_balance_start,
        "my_orders":          show_orders,
        "help":               show_help,
        "admin_panel":        admin_panel,
        "admin_categories":   admin_categories,
        "admin_products_all": admin_products_all,
        "admin_deposits":     admin_deposits,
        "admin_users":        admin_users,
        "admin_stats":        admin_stats,
        "admin_speed_requests": admin_speed_requests,
        "admin_add_category": start_add_category,
    }
    if data in routes:
        await routes[data](update, context); return

    # parameterised routes
    if data.startswith("cat_"):              await show_apps(update, context)
    elif data.startswith("app_"):           await show_products_by_app(update, context)
    elif data.startswith("product_"):       await show_product_detail(update, context)
    elif data.startswith("buy_"):           await buy_product(update, context)
    elif data.startswith("setqty_"):        await select_quantity(update, context)
    elif data.startswith("enterqty_"):      await enter_quantity(update, context)
    elif data == "admin_set_product_type_input": await set_product_type_input(update, context)
    elif data == "admin_set_product_type_ready": await set_product_type_ready(update, context)
    elif data.startswith("admin_set_product_infinite_"): await handle_product_infinite_choice(update, context)
    elif data.startswith("add_order_input_"):
        # user wants to attach a link/account to an existing order
        parts = data.split("_")
        order_id = int(parts[3]) if len(parts) > 3 else int(parts[-1])
        await start_add_order_input(update, context, order_id)
    elif data.startswith("add_purchase_input_"):
        await start_add_purchase_input(update, context)
    elif data.startswith("request_speed_"):
        await request_speed(update, context)
    elif data.startswith("speed_request_detail_"):
        await speed_request_detail(update, context)
    elif data.startswith("admin_set_status_"):
        await admin_set_purchase_status(update, context)
    elif data.startswith("confirmbuy_"):    await confirm_buy(update, context)

    elif data.startswith("complete_order_"): await complete_order(update, context)
    elif data.startswith("reject_purchase_"):
        if data.startswith("reject_purchase_reason_"):
            await execute_reject_purchase(update, context)
        else:
            await reject_purchase(update, context)
    elif data.startswith("order_detail_"):   await order_detail(update, context)

    elif data.startswith("admin_cat_"):     await admin_category_detail(update, context)
    elif data.startswith("admin_del_cat_"): await admin_delete_category(update, context)
    elif data.startswith("admin_add_app_"): await start_add_app(update, context)
    elif data.startswith("admin_app_"):     await admin_app_detail(update, context)
    elif data.startswith("admin_del_app_"): await admin_delete_app(update, context)
    elif data.startswith("admin_add_prod_"):await start_add_product(update, context)
    elif data.startswith("admin_prod_"):
        context.user_data.pop('state', None)
        context.user_data.pop('adding_item_to', None)
        await admin_product_detail(update, context)
    elif data.startswith("admin_delprod_"): await delete_product(update, context)
    elif data.startswith("admin_additem_"): await start_add_item(update, context)
    elif data.startswith("admin_mgitems_"): await manage_items(update, context)
    elif data.startswith("admin_delitem_"): await delete_item(update, context)
    elif data.startswith("admin_view_user_"): await admin_view_user(update, context)
    elif data.startswith("admin_reset_user_balance_"): await admin_reset_user_balance(update, context)
    elif data.startswith("admin_edit_user_balance_"): await admin_edit_user_balance(update, context)
    elif data.startswith("admin_delete_user_"): await admin_delete_user(update, context)
    elif data == "admin_broadcast":
      await start_broadcast(update, context)
    elif data.startswith("admin_orders"):    await admin_orders(update, context)
    return

# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, receive_payment_proof))
    print("🤖 البوت شغال...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
    
