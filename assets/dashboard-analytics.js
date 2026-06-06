(() => {
  const root = document.querySelector('[data-dashboard-analytics]');
  if (!root) return;

  const numberFormat = new Intl.NumberFormat(document.documentElement.lang || 'az');
  const setText = (selector, value) => {
    const element = root.querySelector(selector);
    if (element) element.textContent = value;
  };
  const formatNumber = (value) => numberFormat.format(Number(value || 0));
  const escapeHtml = (value) => String(value || '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

  const formatTime = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return date.toLocaleTimeString(document.documentElement.lang || 'az', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const updateMeters = (payload) => {
    const metrics = {
      'health.cpu': payload.vps_health?.cpu_usage || 0,
      'health.ram': payload.vps_health?.ram_usage || 0,
      'health.disk': payload.vps_health?.disk_usage || 0,
    };
    Object.entries(metrics).forEach(([key, value]) => {
      const meter = root.querySelector(`[data-meter="${key}"]`);
      if (meter) meter.style.width = `${Math.min(100, Math.max(0, value))}%`;
    });
  };

  const updateHealth = (payload) => {
    setText('[data-analytics-value="health.cpu"]', payload.vps_health?.cpu_usage ?? '—');
    setText('[data-analytics-value="health.ram"]', payload.vps_health?.ram_usage ?? '—');
    setText('[data-analytics-value="health.disk"]', payload.vps_health?.disk_usage ?? '—');
    setText('[data-analytics-value="health.uptime"]', payload.vps_health?.uptime || '—');
    const status = payload.vps_health?.status || 'healthy';
    const badge = root.querySelector('[data-health-status]');
    if (badge) {
      badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
      badge.dataset.status = status;
    }
    updateMeters(payload);
  };

  const updateOnlineVisitors = (payload) => {
    setText('[data-analytics-value="online.current"]', formatNumber(payload.online_visitors?.current));
    setText('[data-analytics-value="online.last_5_min"]', formatNumber(payload.online_visitors?.last_5_min));
    setText('[data-analytics-value="online.last_15_min"]', formatNumber(payload.online_visitors?.last_15_min));
    setText('[data-analytics-value="online.last_60_min"]', formatNumber(payload.online_visitors?.last_60_min));
    setText('[data-analytics-value="generated_at"]', formatTime(payload.generated_at));
  };

  const updateDevices = (payload) => {
    const devices = payload.device_statistics || [];
    const lookup = Object.fromEntries(devices.map((item) => [item.key, item.percent]));
    ['mobile', 'desktop', 'tablet'].forEach((key) => {
      const element = root.querySelector(`[data-device-percent="${key}"]`);
      if (element) element.textContent = `${lookup[key] || 0}%`;
    });
    const mobile = lookup.mobile || 0;
    const desktop = lookup.desktop || 0;
    const tablet = lookup.tablet || 0;
    const chart = root.querySelector('[data-device-chart]');
    if (chart) {
      chart.style.background = `conic-gradient(#48a6ff 0 ${mobile}%, #7c5cff ${mobile}% ${mobile + desktop}%, #35d49a ${mobile + desktop}% ${mobile + desktop + tablet}%, rgba(255,255,255,.08) 0)`;
    }
  };

  const updateCountries = (payload) => {
    const list = root.querySelector('[data-country-list]');
    if (!list) return;
    const countries = payload.top_countries || [];
    if (!countries.length) {
      list.innerHTML = '<p class="muted">Country traffic will appear after visitors are recorded.</p>';
      return;
    }
    list.innerHTML = countries.map((country) => `
      <div class="country-row">
        <span class="country-flag" aria-hidden="true">${escapeHtml(country.flag || '🌐')}</span>
        <div>
          <strong>${escapeHtml(country.name || 'Unknown')}</strong>
          <span class="progress"><span style="width:${country.percent || 0}%"></span></span>
        </div>
        <em>${country.percent || 0}%</em>
      </div>
    `).join('');
  };

  const applyTranslations = () => {
    const i18n = window.VREYCAdminI18n;
    if (i18n) i18n.applyLanguage(i18n.getLanguage());
  };

  const refresh = async () => {
    try {
      const response = await fetch('/admin/dashboard/analytics', { credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Dashboard analytics failed with HTTP ${response.status}`);
      const payload = await response.json();
      updateOnlineVisitors(payload);
      updateHealth(payload);
      updateDevices(payload);
      updateCountries(payload);
      applyTranslations();
      root.dataset.loaded = 'true';
    } catch (error) {
      root.dataset.loaded = 'error';
      setText('[data-analytics-value="generated_at"]', 'Unavailable');
    }
  };

  document.addEventListener('DOMContentLoaded', refresh);
  setInterval(refresh, 30000);
})();
