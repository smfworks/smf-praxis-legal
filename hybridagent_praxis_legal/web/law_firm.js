/* Praxis Law Firm pack dashboard — the four compliance surfaces.
 * Polls /api/law_firm every 20s; renders only when the law_firm pack is active.
 * Surfaces: matter-hold badge, credential compliance card, ad-filing tracker,
 *           security attestation panel.
 * Served from /web/law_firm.js.
 */
(function () {
  "use strict";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>\"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }
  async function api(url) {
    var r = await fetch(url);
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  var mount = null, section = null, data = null;

  function renderSurface(tag, title, bodyHtml) {
    var s = el("div", "lf-surface");
    s.appendChild(el("h3", "lf-surface-title", esc(title)));
    s.appendChild(el("div", "lf-surface-body", bodyHtml));
    return s;
  }

  function renderMatterHolds(h) {
    if (!h || h.error) return '<div class="lf-empty">—</div>';
    var html = '<div class="lf-stat-line"><span class="lf-stat">' +
      h.active + ' active</span> / <span>' + h.total + ' total</span></div>';
    if (h.matters && h.matters.length) {
      html += '<ul class="lf-list">';
      h.matters.forEach(function (m) {
        html += '<li><span class="lf-badge lf-badge-' +
          (m.status === "acknowledged" ? "ok" : "warn") + '">' +
          esc(m.status) + '</span> ' + esc(m.matter_id) +
          ' <span class="lf-muted">' + esc(m.scope).slice(0, 50) + '</span></li>';
      });
      html += '</ul>';
    }
    return html;
  }

  function renderCredentials(c) {
    if (!c || c.error) return '<div class="lf-empty">—</div>';
    var html = '<div class="lf-stat-line">';
    ["current", "expiring_soon", "expired", "ce_deficient", "no_requirement"]
      .forEach(function (k) {
        if (c[k] != null) {
          var cls = k === "current" || k === "no_requirement" ? "ok" :
                    k === "expired" || k === "ce_deficient" ? "bad" : "warn";
          html += '<span class="lf-stat lf-stat-' + cls + '">' + c[k] + ' ' +
            k.replace(/_/g, " ") + '</span>';
        }
      });
    html += '</div>';
    if (c.credentials && c.credentials.length) {
      html += '<ul class="lf-list">';
      c.credentials.forEach(function (cr) {
        html += '<li><span class="lf-badge lf-badge-' +
          (cr.status === "current" || cr.status === "no_requirement" ? "ok" :
           cr.status === "expired" || cr.status === "ce_deficient" ? "bad" : "warn") +
          '">' + esc(cr.status) + '</span> ' + esc(cr.user_id) + ' ' +
          esc(cr.profession) + ' ' + esc(cr.state) +
          ' <span class="lf-muted">' + cr.accumulated + '/' + cr.required + ' hrs</span></li>';
      });
      html += '</ul>';
    }
    return html;
  }

  function renderAdFilings(f) {
    if (!f || f.error) return '<div class="lf-empty">—</div>';
    var html = '<div class="lf-stat-line"><span class="lf-stat">' + f.total +
      ' filings</span></div>';
    if (f.ny) html += '<div class="lf-row">NY: ' + f.ny.compliant + '/' +
      f.ny.total + ' compliant</div>';
    if (f.fl) html += '<div class="lf-row">FL: ' + f.fl.compliant + '/' +
      f.fl.total + ' compliant</div>';
    return html;
  }

  function renderAttestations(a) {
    if (!a || !a.jurisdictions || !a.jurisdictions.length)
      return '<div class="lf-empty">—</div>';
    var html = '<ul class="lf-list">';
    a.jurisdictions.forEach(function (j) {
      var cls = j.passed ? "ok" : (j.critical > 0 ? "bad" : "warn");
      html += '<li><span class="lf-badge lf-badge-' + cls + '">' +
        (j.passed ? "PASS" : "FAIL") + '</span> ' + esc(j.state) +
        ' <span class="lf-muted">' + esc(j.tier).replace(/_/g, " ") +
        ' (' + j.findings + ' findings, ' + j.critical + ' critical)</span></li>';
    });
    html += '</ul>';
    return html;
  }

  function render() {
    if (!data || !data.active) {
      if (section) section.hidden = true;
      return;
    }
    if (section) section.hidden = false;
    if (!mount) return;
    mount.innerHTML = "";
    mount.appendChild(renderSurface("holds", "Matter Holds", renderMatterHolds(data.matter_holds)));
    mount.appendChild(renderSurface("creds", "Credential Compliance", renderCredentials(data.credentials)));
    mount.appendChild(renderSurface("filings", "Ad-Filing Tracker", renderAdFilings(data.ad_filings)));
    mount.appendChild(renderSurface("attest", "Security Attestation", renderAttestations(data.security_attestations)));
  }

  async function load() {
    try {
      data = await api("/api/law_firm");
      render();
    } catch (e) {
      if (mount) mount.innerHTML = '<div class="lf-empty">Compliance data unavailable.</div>';
    }
  }

  function init() {
    section = document.getElementById("law-firm-section");
    mount = document.getElementById("law-firm-mount");
    if (!section || !mount) return;
    load();
    setInterval(load, 20000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();