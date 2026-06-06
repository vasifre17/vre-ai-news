(() => {
  const STORAGE_KEY = 'vreycAdminLanguage';
  const DEFAULT_LANGUAGE = 'az';
  const SUPPORTED_LANGUAGES = ['az', 'en'];

  const translations = {
    az: {
      // Admin navigation
      'Dashboard': 'İdarə paneli',
      'Articles': 'Xəbərlər',
      'Categories': 'Kateqoriyalar',
      'Media Library': 'Media kitabxanası',
      'AI Translations': 'AI tərcümələr',
      'SEO Diagnostics': 'SEO diaqnostika',
      'Settings': 'Parametrlər',

      // Required common actions and labels
      'View site': 'Sayta bax',
      'Logout': 'Çıxış',
      'Create article': 'Xəbər yarat',
      'Save': 'Yadda saxla',
      'Delete': 'Sil',
      'Edit': 'Redaktə et',
      'View': 'Bax',
      'Preview': 'Önizlə',
      'Copy URL': 'URL kopyala',
      'Apply filters': 'Filtrləri tətbiq et',
      'Reset': 'Sıfırla',
      'Search articles': 'Xəbərlərdə axtar',
      'All categories': 'Bütün kateqoriyalar',
      'All languages': 'Bütün dillər',
      'All statuses': 'Bütün statuslar',
      'Newest first': 'Ən yenilər əvvəl',
      'Published': 'Yayında',
      'Drafts': 'Qaralamalar',
      'Scheduled': 'Planlaşdırılmış',
      'Bulk action': 'Toplu əməliyyat',
      'Bulk action…': 'Toplu əməliyyat…',
      'Apply to selected': 'Seçilənlərə tətbiq et',

      // Frequently used admin text kept small and easy to expand.
      'Draft': 'Qaralama',
      'All': 'Hamısı',
      'Category': 'Kateqoriya',
      'Language': 'Dil',
      'Status': 'Status',
      'Sort': 'Sıralama',
      'From': 'Başlanğıc',
      'To': 'Son',
      'Per page': 'Səhifə üzrə',
      'Title': 'Başlıq',
      'Publish at': 'Yayın vaxtı',
      'Views': 'Baxışlar',
      'Updated': 'Yenilənib',
      'Homepage': 'Ana səhifə',
      'Languages': 'Dillər',
      'Narration': 'Səsləndirmə',
      'Actions': 'Əməliyyatlar',
      'Analytics': 'Analitika',
      'Publish': 'Yayınla',
      'Unpublish': 'Yayından çıxar',
      'New article': 'Yeni xəbər',
      'Edit article': 'Xəbəri redaktə et',
      'Back to articles': 'Xəbərlərə qayıt',
      'Save article': 'Xəbəri yadda saxla',
      'Save settings': 'Parametrləri yadda saxla',
      'Save SEO settings': 'SEO parametrlərini yadda saxla',
      'Apply': 'Tətbiq et',
      'Oldest first': 'Ən köhnələr əvvəl',
      'Most viewed': 'Ən çox baxılan',
      'Most recently updated': 'Ən son yenilənən',
      'Bulk publish': 'Toplu yayınla',
      'Bulk unpublish': 'Toplu yayından çıxar',
      'Bulk category change': 'Toplu kateqoriya dəyişikliyi',
      'Bulk delete': 'Toplu sil',
      'Choose category for category change': 'Kateqoriya dəyişikliyi üçün kateqoriya seçin',
      'Select all articles on page': 'Səhifədəki bütün xəbərləri seç',
      'Instant search by title, slug or content': 'Başlıq, slug və ya məzmunda ani axtarış',
      'Type DELETE for bulk delete': 'Toplu silmə üçün DELETE yazın',
      'Premium newsroom console': 'Premium xəbər otağı konsolu',
      'Premium Newsroom Console': 'Premium xəbər otağı konsolu',
      'Article management': 'Xəbər idarəetməsi',
      'Editorial articles': 'Redaksiya xəbərləri',
      'AI translations': 'AI tərcümələr',
      'SEO diagnostics': 'SEO diaqnostika',
      'User & SEO settings': 'İstifadəçi və SEO parametrləri',
      'Media library': 'Media kitabxanası',
      'Category manager': 'Kateqoriya meneceri',
      'Vasif REYC Admin': 'Vasif REYC Admin',
      'Secure admin access': 'Təhlükəsiz admin girişi',
      'Welcome back': 'Xoş gəlmisiniz',
      'Sign in to continue to the premium newsroom console.': 'Premium xəbər otağı konsoluna davam etmək üçün daxil olun.',
      'Secure access for managing VREYC editorial operations, publishing workflows, and newsroom quality controls.': 'VREYC redaksiya əməliyyatlarını, yayın proseslərini və xəbər otağı keyfiyyət nəzarətini idarə etmək üçün təhlükəsiz giriş.',
      'Username': 'İstifadəçi adı',
      'Password': 'Şifrə',
      'Remember me': 'Məni yadda saxla',
      'Login': 'Daxil ol',
      'Wrong username or password': 'İstifadəçi adı və ya şifrə yanlışdır',
      'Server Online': 'Server aktivdir',
      'SEO Active': 'SEO aktivdir',
      'Security Enabled': 'Təhlükəsizlik aktivdir',
      'Show password': 'Şifrəni göstər',
      'Hide password': 'Şifrəni gizlət',
      'Dashboard | VREYC Admin': 'İdarə paneli | VREYC Admin',
      'Dashboard 2.0 | VREYC Admin': 'İdarə paneli 2.0 | VREYC Admin',
      'VREYC Admin Dashboard': 'VREYC Admin idarə paneli',
      'VREYC Admin Dashboard 2.0': 'VREYC Admin idarə paneli 2.0',
      'Premium newsroom command center': 'Premium xəbər otağı komanda mərkəzi',
      'Dashboard 2.0': 'İdarə paneli 2.0',
      'A cleaner desktop grid and mobile-first control center for analytics, SEO, system health, and editorial workflow.': 'Analitika, SEO, sistem sağlamlığı və redaksiya prosesi üçün daha təmiz masaüstü şəbəkə və mobilə uyğun idarə mərkəzi.',
      'SEO diagnostics': 'SEO diaqnostika',
      'Total articles': 'Ümumi xəbərlər',
      'Total views': 'Ümumi baxışlar',
      'Views today': 'Bugünkü baxışlar',
      'Views last 7 days': 'Son 7 günün baxışları',
      'Views last 30 days': 'Son 30 günün baxışları',
      'Unique visitors': 'Unikal ziyarətçilər',
      'Returning visitors': 'Qayıdan ziyarətçilər',
      'SEO health score': 'SEO sağlamlıq balı',
      'Google News status': 'Google News statusu',
      'AdSense status': 'AdSense statusu',
      'Editorial inventory': 'Redaksiya inventarı',
      'Real tracked views': 'Real izlənən baxışlar',
      'Since 00:00 UTC': '00:00 UTC vaxtından',
      'Rolling weekly traffic': 'Davamlı həftəlik trafik',
      'Rolling monthly traffic': 'Davamlı aylıq trafik',
      'Distinct visitor fingerprints': 'Fərqli ziyarətçi izləri',
      'Visitors with 2+ article views': '2+ xəbər baxışı olan ziyarətçilər',
      'Average article SEO audit': 'Orta xəbər SEO auditi',
      'Based on published SEO readiness': 'Yayındakı SEO hazırlığı əsasında',
      'Publisher ID configuration': 'Publisher ID konfiqurasiyası',
      'Google & SEO': 'Google və SEO',
      'Google & SEO status panel': 'Google və SEO status paneli',
      'Open diagnostics': 'Diaqnostikanı aç',
      'XML sitemap status': 'XML sitemap statusu',
      'News sitemap status': 'News sitemap statusu',
      'RSS feed status': 'RSS feed statusu',
      'Last sitemap refresh': 'Son sitemap yenilənməsi',
      'Missing meta descriptions': 'Çatışmayan meta təsvirlər',
      'Missing hreflang': 'Çatışmayan hreflang',
      'Infrastructure': 'İnfrastruktur',
      'System health panel': 'Sistem sağlamlığı paneli',
      'Server status': 'Server statusu',
      'Security status': 'Təhlükəsizlik statusu',
      'Upload limit': 'Yükləmə limiti',
      'Protected routes': 'Qorunan marşrutlar',
      'Editorial': 'Redaksiya',
      'Editorial workflow panel': 'Redaksiya iş prosesi paneli',
      'Published articles': 'Yayındakı xəbərlər',
      'Draft articles': 'Qaralama xəbərlər',
      'Scheduled articles': 'Planlaşdırılmış xəbərlər',
      'Latest article date': 'Ən son xəbər tarixi',
      'Publish due scheduled articles now': 'Vaxtı çatmış planlaşdırılmış xəbərləri indi yayınla',
      'Activity': 'Fəaliyyət',
      'Latest activity panel': 'Son fəaliyyət paneli',
      'Article published': 'Xəbər yayınlandı',
      'Image uploaded': 'Şəkil yükləndi',
      'SEO scan completed': 'SEO skan tamamlandı',
      'Sitemap refreshed': 'Sitemap yeniləndi',
      'Latest media library upload': 'Media kitabxanasına son yükləmə',
      'Traffic': 'Trafik',
      'Traffic overview panel': 'Trafik icmalı paneli',
      'Daily views chart, weekly views chart, and monthly views chart from article analytics.': 'Xəbər analitikasından gündəlik, həftəlik və aylıq baxış qrafikləri.',
      'Daily views': 'Gündəlik baxışlar',
      'Weekly views': 'Həftəlik baxışlar',
      'Monthly views': 'Aylıq baxışlar',
      'Audience': 'Auditoriya',
      'Top 10 most viewed articles': 'Ən çox baxılan 10 xəbər',
      'Open report': 'Hesabatı aç',
      'Top categories': 'Ən populyar kateqoriyalar',
      'Manage': 'İdarə et',
      'Recently created': 'Son yaradılanlar',
      'Latest 10 articles': 'Son 10 xəbər',
      'Manage all': 'Hamısını idarə et',
      'Visitors': 'Ziyarətçilər',
      'Visitor statistics': 'Ziyarətçi statistikası',
      'Distinct article readers': 'Fərqli xəbər oxucuları',
      'Repeat article readers': 'Təkrar xəbər oxucuları',
      'All tracked article views': 'Bütün izlənən xəbər baxışları',
      'Current-day performance': 'Cari gün performansı',
      'Schedule': 'Plan',
      'Next scheduled article': 'Növbəti planlaşdırılmış xəbər',
      'View scheduled': 'Planlaşdırılmışlara bax',
      'Pipeline': 'Pipeline',
      'System activity': 'Sistem fəaliyyəti',
      'Ready': 'Hazırdır',
      'Needs review': 'Yoxlama lazımdır',
      'Configured': 'Konfiqurasiya edilib',
      'Missing': 'Çatışmır',
      'Active': 'Aktivdir',
      'Waiting for published articles': 'Yayındakı xəbərlər gözlənilir',
      'Online': 'Onlayn',
      'Enabled': 'Aktivdir',
      'Review secret key': 'Secret key yoxlanmalıdır',
      'No article views recorded yet.': 'Hələ xəbər baxışı qeydə alınmayıb.',
      'Category traffic will appear after articles are viewed.': 'Xəbərlərə baxış olduqdan sonra kateqoriya trafiki görünəcək.',
      'No articles yet.': 'Hələ xəbər yoxdur.',
      'No scheduled article is queued.': 'Planlaşdırılmış xəbər növbədə yoxdur.',
      'No pipeline logs yet.': 'Hələ pipeline jurnalı yoxdur.',

      'Dashboard 3.0 | VREYC Admin': 'İdarə paneli 3.0 | VREYC Admin',
      'VREYC Admin Dashboard 3.0': 'VREYC Admin idarə paneli 3.0',
      'Dashboard 3.0': 'İdarə paneli 3.0',
      'A cleaner desktop grid and mobile-first control center for real-time analytics, SEO, system health, and editorial workflow.': 'Real vaxt analitikası, SEO, sistem sağlamlığı və redaksiya iş axını üçün daha təmiz desktop şəbəkəsi və mobil-yönümlü idarə mərkəzi.',
      'Live audience': 'Canlı auditoriya',
      'Real-time online visitors': 'Real vaxt onlayn ziyarətçilər',
      'Refreshes automatically every 30 seconds.': 'Hər 30 saniyədən bir avtomatik yenilənir.',
      'Live': 'Canlı',
      'Current active visitors': 'Hazırda aktiv ziyarətçilər',
      'Last 5 min': 'Son 5 dəq',
      'Last 15 min': 'Son 15 dəq',
      'Last 60 min': 'Son 60 dəq',
      'Last refreshed:': 'Son yenilənmə:',
      'Loading…': 'Yüklənir…',
      'VPS health monitor': 'VPS sağlamlıq monitoru',
      'Checking': 'Yoxlanılır',
      'Healthy': 'Sağlam',
      'Warning': 'Xəbərdarlıq',
      'Critical': 'Kritik',
      'CPU usage': 'CPU istifadəsi',
      'RAM usage': 'RAM istifadəsi',
      'Disk usage': 'Disk istifadəsi',
      'Server uptime': 'Server işləmə müddəti',
      'Devices': 'Cihazlar',
      'Device statistics': 'Cihaz statistikası',
      'Device traffic breakdown chart': 'Cihaz trafiki bölgüsü qrafiki',
      'Mobile': 'Mobil',
      'Desktop': 'Desktop',
      'Tablet': 'Planşet',
      'Geography': 'Coğrafiya',
      'Top countries': 'Top ölkələr',
      'Loading country traffic…': 'Ölkə trafiki yüklənir…',
      'Country traffic will appear after visitors are recorded.': 'Ziyarətçilər qeydə alındıqdan sonra ölkə trafiki görünəcək.',
      'Unavailable': 'Əlçatan deyil',
      'Copied!': 'Kopyalandı!',
      'Copied': 'Kopyalandı'
    },
    en: {}
  };

  const textNodeOriginals = new WeakMap();
  const translatedAttributes = ['placeholder', 'aria-label', 'title'];

  const normalizeLanguage = (value) => SUPPORTED_LANGUAGES.includes(value) ? value : DEFAULT_LANGUAGE;

  const getStoredLanguage = () => {
    try {
      return normalizeLanguage(window.localStorage.getItem(STORAGE_KEY) || DEFAULT_LANGUAGE);
    } catch (error) {
      return DEFAULT_LANGUAGE;
    }
  };

  const storeLanguage = (language) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, language);
    } catch (error) {
      // localStorage can be unavailable in restricted browser contexts; keep the in-page toggle working.
    }
  };

  const preserveSpacing = (original, translated) => {
    const leading = original.match(/^\s*/)?.[0] || '';
    const trailing = original.match(/\s*$/)?.[0] || '';
    return `${leading}${translated}${trailing}`;
  };

  const translateValue = (source, language) => {
    if (language === 'en') return source;
    return translations[language]?.[source.trim()] || source;
  };

  const shouldSkipNode = (node) => {
    const parent = node.parentElement;
    if (!parent) return true;
    return Boolean(parent.closest('script, style, textarea, code, pre, [contenteditable="true"], [data-i18n-skip]'));
  };

  const applyTextTranslations = (language) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (shouldSkipNode(node) || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });

    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach((node) => {
      if (!textNodeOriginals.has(node)) textNodeOriginals.set(node, node.nodeValue);
      const original = textNodeOriginals.get(node);
      const translated = translateValue(original, language);
      node.nodeValue = preserveSpacing(original, translated);
    });
  };

  const applyAttributeTranslations = (language) => {
    document.querySelectorAll('[placeholder], [aria-label], [title]').forEach((element) => {
      if (element.closest('[data-i18n-skip]')) return;
      translatedAttributes.forEach((attribute) => {
        if (!element.hasAttribute(attribute)) return;
        const dataAttribute = `i18nOriginal${attribute.replace(/(^|-)(\w)/g, (_, _dash, char) => char.toUpperCase())}`;
        if (!element.dataset[dataAttribute]) element.dataset[dataAttribute] = element.getAttribute(attribute);
        element.setAttribute(attribute, translateValue(element.dataset[dataAttribute], language));
      });
    });
  };

  const updateSwitcherState = (language) => {
    document.documentElement.lang = language;
    document.querySelectorAll('[data-admin-language-option]').forEach((button) => {
      const active = button.dataset.adminLanguageOption === language;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  };

  const applyLanguage = (language) => {
    const normalized = normalizeLanguage(language);
    applyTextTranslations(normalized);
    applyAttributeTranslations(normalized);
    updateSwitcherState(normalized);
    window.dispatchEvent(new CustomEvent('admin-language-change', { detail: { language: normalized } }));
  };

  const initializeSwitcher = () => {
    document.querySelectorAll('[data-admin-language-option]').forEach((button) => {
      button.addEventListener('click', () => {
        const language = normalizeLanguage(button.dataset.adminLanguageOption);
        storeLanguage(language);
        applyLanguage(language);
      });
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    initializeSwitcher();
    applyLanguage(getStoredLanguage());
  });

  window.VREYCAdminI18n = {
    applyLanguage,
    getLanguage: getStoredLanguage,
    translate: translateValue,
    translations
  };
})();
