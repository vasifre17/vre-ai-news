SUPPORTED_LANGUAGES = ["az", "en", "ru", "tr", "zh", "es"]
LANGUAGE_LABELS = {"az": "AZ", "en": "EN", "ru": "RU", "tr": "TR", "zh": "中文", "es": "ES"}
DEFAULT_LANGUAGE = "az"

UI_TEXT = {
    "home": {"az": "Ana səhifə", "en": "Home", "ru": "Главная", "tr": "Ana Sayfa", "zh": "首页", "es": "Inicio"},
    "search": {"az": "Axtar", "en": "Search", "ru": "Поиск", "tr": "Ara", "zh": "搜索", "es": "Buscar"},
    "no_articles": {"az": "Hələlik dərc edilmiş məqalə yoxdur. Zəhmət olmasa sonra yenidən yoxlayın.", "en": "No published articles yet. Please check back soon.", "ru": "Пока нет опубликованных статей. Пожалуйста, зайдите позже.", "tr": "Henüz yayınlanmış makale yok. Lütfen daha sonra tekrar kontrol edin.", "zh": "暂无已发布文章，请稍后再查看。", "es": "Aún no hay artículos publicados. Vuelve a consultarlo pronto."},
    "go_home": {"az": "Ana səhifəyə qayıt", "en": "Go home", "ru": "На главную", "tr": "Ana sayfaya dön", "zh": "返回首页", "es": "Ir al inicio"},
    "page_not_found": {"az": "Səhifə tapılmadı.", "en": "Page not found.", "ru": "Страница не найдена.", "tr": "Sayfa bulunamadı.", "zh": "页面未找到。", "es": "Página no encontrada."},
    "server_error": {"az": "Xəta baş verdi.", "en": "Something went wrong.", "ru": "Что-то пошло не так.", "tr": "Bir şeyler ters gitti.", "zh": "出现错误。", "es": "Algo salió mal."},
}

CATEGORIES = {
    "Politics": {"az": "Siyasət", "en": "Politics", "ru": "Политика", "tr": "Siyaset", "zh": "政治", "es": "Política"},
    "World": {"az": "Dünya", "en": "World", "ru": "Мир", "tr": "Dünya", "zh": "国际", "es": "Mundo"},
    "Social": {"az": "Cəmiyyət", "en": "Social", "ru": "Общество", "tr": "Toplum", "zh": "社会", "es": "Sociedad"},
    "Economy": {"az": "İqtisadiyyat", "en": "Economy", "ru": "Экономика", "tr": "Ekonomi", "zh": "经济", "es": "Economía"},
}

def t(key: str, lang: str) -> str:
    return UI_TEXT.get(key, {}).get(lang) or UI_TEXT.get(key, {}).get(DEFAULT_LANGUAGE, key)

def category_label(category: str, lang: str) -> str:
    return CATEGORIES.get(category, {}).get(lang, category)
