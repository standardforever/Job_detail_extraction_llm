async def page_extraction() -> str:
    js_code = r"""
        ({ sections } = {}) => {
            const selectorMap = {};

            function stableId(path) {
                let hash = 0;
                for (let index = 0; index < path.length; index += 1) {
                    hash = ((hash << 5) - hash + path.charCodeAt(index)) | 0;
                }
                return Math.abs(hash % 9000) + 1000;
            }

            function buildDomPath(el) {
                const segments = [];
                let current = el;
                while (current && current instanceof Element) {
                    const tag = current.tagName.toLowerCase();
                    const parent = current.parentElement;
                    if (!parent) {
                        segments.push(`${tag}[0]`);
                        break;
                    }
                    const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
                    segments.push(`${tag}[${Math.max(siblings.indexOf(current), 0)}]`);
                    current = parent;
                }
                return segments.reverse().join('/');
            }

            function cleanAttr(value) {
                return (value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
            }

            function getAttributes(el) {
                const attrs = {};
                for (const attr of Array.from(el.attributes || [])) {
                    if (!attr.value) continue;
                    const attrName = (attr.name || '').toLowerCase();
                    if (
                        ['id', 'name', 'type', 'role', 'placeholder', 'value', 'title', 'alt', 'aria-label', 'aria-expanded', 'aria-haspopup', 'href'].includes(attrName)
                        || attrName.includes('url')
                        || attrName.includes('href')
                        || attrName.includes('link')
                    ) {
                        attrs[attr.name] = cleanAttr(attr.value);
                    }
                }
                return attrs;
            }

            // ── SAFE className getter — works on both HTML and SVG elements ──
            // On SVG, el.className returns SVGAnimatedString, not a string.
            // el.getAttribute('class') always returns a plain string or null.
            function getCls(el) {
                if (!el) return '';
                return el.getAttribute('class') || '';
            }

            // ── Exact class token check — prevents "pp-accordion-button-label"
            // matching a check for "pp-accordion-button" via substring includes() ──
            function hasClass(el, name) {
                const cls = getCls(el);
                if (!cls) return false;
                // Split on whitespace and check for exact token match
                return cls.split(/\s+/).indexOf(name) !== -1;
            }

            // ── Check if any of a list of class names is an exact token match ──
            function hasAnyClass(el, names) {
                const tokens = getCls(el).split(/\s+/);
                return names.some(n => tokens.indexOf(n) !== -1);
            }

            // ── Check if class contains a substring (only for prefix patterns like
            //    "accordion-collapse" which won't have false positives) ──
            function clsIncludes(el, substr) {
                return getCls(el).includes(substr);
            }

            // ════════════════════════════════════════════════════════
            // 1. EXCLUSION — header / footer / top-level nav only
            //
            // We exclude:
            //   - <header> elements (site header)
            //   - <footer> elements (site footer)
            //   - role="banner" / role="contentinfo"
            //   - <nav> elements that are TOP-LEVEL (direct children of body,
            //     or inside header/footer) — i.e. the primary site navigation
            //
            // We DO NOT exclude sidebar <nav> elements inside the main content
            // area — these often contain relevant links (careers pages, job
            // categories, related pages) that the LLM needs to see.
            // ════════════════════════════════════════════════════════
            const excluded = new Set();

            // Always exclude header and footer and their ARIA equivalents
            ['header','footer','[role="banner"]','[role="contentinfo"]']
                .forEach(sel => document.querySelectorAll(sel).forEach(el => excluded.add(el)));

            // Only exclude NAV elements that are top-level (not inside main content)
            // A nav is "top-level" if its closest landmark ancestor is body, header, or footer
            // i.e. it is NOT inside main, article, section, aside, or a content div
            const CONTENT_LANDMARKS = new Set(['main','article','section','aside']);
            document.querySelectorAll('nav, [role="navigation"]').forEach(nav => {
                // Walk up to find the nearest landmark ancestor
                let ancestor = nav.parentElement;
                let isInsideContent = false;
                while (ancestor && ancestor !== document.body) {
                    const aTag = ancestor.tagName.toLowerCase();
                    const aRole = (ancestor.getAttribute('role') || '').toLowerCase();
                    if (CONTENT_LANDMARKS.has(aTag) || CONTENT_LANDMARKS.has(aRole)) {
                        isInsideContent = true;
                        break;
                    }
                    // Also check: if the ancestor has an id/class suggesting main content
                    const aId = (ancestor.getAttribute('id') || '').toLowerCase();
                    const aCls = (ancestor.getAttribute('class') || '').toLowerCase();
                    if (
                        aId.includes('content') || aId.includes('main') || aId.includes('body') ||
                        aCls.includes('content') || aCls.includes('main-area') || aCls.includes('page-body')
                    ) {
                        isInsideContent = true;
                        break;
                    }
                    ancestor = ancestor.parentElement;
                }
                if (!isInsideContent) {
                    excluded.add(nav);
                }
            });

            function isExcluded(el) {
                let node = el;
                while (node && node !== document.body) {
                    if (excluded.has(node)) return true;
                    node = node.parentElement;
                }
                return false;
            }

            // ════════════════════════════════════════════════════════
            // 2. PANEL REGISTRY
            // Pre-scan DOM and register every hidden/collapsed panel.
            // ════════════════════════════════════════════════════════
            const panelById = new Map();
            const panelSet  = new Set();

            function registerPanel(el) {
                if (!el || panelSet.has(el)) return;
                panelSet.add(el);
                const id = el.getAttribute('id');
                if (id) panelById.set(id, el);
            }

            document.querySelectorAll('*').forEach(el => {
                const cls  = getCls(el);
                const role = el.getAttribute('role') || '';
                const tag  = el.tagName.toLowerCase();

                if (hasClass(el, 'accordion-collapse') || el.hasAttribute('data-bs-parent')) {
                    registerPanel(el); return;
                }
                if (el.hasAttribute('data-tab-content')) {
                    registerPanel(el); return;
                }
                if ((role === 'region' || role === 'tabpanel') && el.getAttribute('aria-hidden') === 'true') {
                    registerPanel(el); return;
                }
                if (hasAnyClass(el, ['elementor-tab-content','elementor-toggle-content'])) {
                    registerPanel(el); return;
                }
                const panelClasses = [
                    'accordion-content','accordion-body','accordion-panel',
                    'toggle-content','panel-body','tab-content',
                    'pp-accordion-content','vc_tta_content','divi-toggle__content',
                    'jet-accordion__item-content','wc-tabs-content',
                ];
                if (hasAnyClass(el, panelClasses)) {
                    registerPanel(el); return;
                }
                if (tag === 'details') registerPanel(el);
            });

            // Register panels referenced by any trigger
            document.querySelectorAll('[aria-controls],[data-bs-target],[data-target]').forEach(trigger => {
                const ref = trigger.getAttribute('aria-controls') ||
                            (trigger.getAttribute('data-bs-target') || '').replace('#','') ||
                            (trigger.getAttribute('data-target') || '').replace('#','');
                if (ref) {
                    const panel = document.getElementById(ref);
                    if (panel) registerPanel(panel);
                }
            });

            // CSS radio/checkbox tab pattern (no JS, pure CSS sibling selector)
            // e.g. Bishop Luffa: input.tabclass + div { display:none }
            //                    input.tabclass:checked + div { display:block }
            // The panel is the immediate next-sibling div of a hidden radio/checkbox input.
            document.querySelectorAll('input[type="radio"], input[type="checkbox"]').forEach(inp => {
                const s = window.getComputedStyle(inp);
                if (s.display === 'none' || inp.getAttribute('style') === 'display:none' ||
                    inp.hasAttribute('hidden')) {
                    // Check if its next sibling is a div/section that is also hidden
                    let sib = inp.nextElementSibling;
                    if (sib && (sib.tagName === 'DIV' || sib.tagName === 'SECTION' || sib.tagName === 'ARTICLE')) {
                        const ss = window.getComputedStyle(sib);
                        if (ss.display === 'none') {
                            registerPanel(sib);
                        }
                    }
                }
            });

            // Also: label[for=X] where X is an input that controls a hidden panel
            // These labels act as toggle triggers for CSS-only accordions
            document.querySelectorAll('label[for]').forEach(lbl => {
                const targetId = lbl.getAttribute('for');
                const input = document.getElementById(targetId);
                if (input && (input.type === 'radio' || input.type === 'checkbox')) {
                    // Find the panel this input controls (next sibling div of the input)
                    let sib = input.nextElementSibling;
                    if (sib && panelSet.has(sib)) {
                        // This label is a CSS-accordion trigger — register a mapping
                        lbl._cssAccordionPanel = sib;
                    }
                }
            });

            // ════════════════════════════════════════════════════════
            // 3. TRIGGER DETECTION
            // ════════════════════════════════════════════════════════
            function getTriggerType(el) {
                const tag      = el.tagName.toLowerCase();
                const cls      = getCls(el);
                const bsToggle = el.getAttribute('data-bs-toggle') || el.getAttribute('data-toggle') || '';
                const role     = el.getAttribute('role') || '';

                if (bsToggle === 'collapse' || bsToggle === 'tab' || bsToggle === 'modal') return 'dropdown';
                if (hasClass(el, 'accordion-title')) return 'dropdown';
                if (tag === 'summary') return 'dropdown';

                const ariaControls = el.getAttribute('aria-controls');
                if (ariaControls) {
                    // Check registry first, fall back to getElementById
                    const ariaPanel = panelById.get(ariaControls) || document.getElementById(ariaControls);
                    if (ariaPanel && !isExcluded(ariaPanel)) {
                        // Register it now if missed
                        if (!panelById.has(ariaControls)) registerPanel(ariaPanel);
                        return 'dropdown';
                    }
                }

                if (el.hasAttribute('aria-expanded')) {
                    const ref = (el.getAttribute('data-bs-target') || el.getAttribute('data-target') || '').replace('#','');
                    if (ref && panelById.has(ref)) return 'dropdown';
                }

                if (hasAnyClass(el, ['elementor-tab-title','elementor-toggle-title'])) return 'dropdown';

                // Use exact token matching to avoid false positives
                // e.g. "pp-accordion-button-label" must NOT match "pp-accordion-button"
                const triggerClasses = [
                    'pp-accordion-button','accordion-button',
                    'vc_tta_title','et_pb_toggle_title','jet-accordion__item-trigger',
                ];
                if (hasAnyClass(el, triggerClasses)) return 'dropdown';

                // CSS radio/checkbox accordion: label[for=X] where X controls a hidden panel
                if (tag === 'label' && el._cssAccordionPanel) return 'dropdown';

                return null;
            }

            // ════════════════════════════════════════════════════════
            // 4. PANEL FINDER
            // ════════════════════════════════════════════════════════
            function findPanel(triggerEl) {
                const tag = triggerEl.tagName.toLowerCase();
                const cls = getCls(triggerEl);

                // aria-controls (most reliable)
                const ariaControls = triggerEl.getAttribute('aria-controls');
                if (ariaControls) {
                    const p = document.getElementById(ariaControls);
                    if (p) return p;
                }

                // data-bs-target / data-target
                const bsTarget = (triggerEl.getAttribute('data-bs-target') || triggerEl.getAttribute('data-target') || '').replace('#','');
                if (bsTarget) {
                    const p = document.getElementById(bsTarget);
                    if (p) return p;
                }

                // HTML5 summary → parent details
                if (tag === 'summary') return triggerEl.closest('details');

                // Foundation accordion-title → sibling [data-tab-content]
                if (hasClass(el, 'accordion-title')) {
                    const li = triggerEl.closest('[data-accordion-item]');
                    if (li) {
                        const p = li.querySelector('[data-tab-content]');
                        if (p) return p;
                    }
                    let sib = triggerEl.nextElementSibling;
                    while (sib) {
                        if (sib.hasAttribute('data-tab-content') || getCls(sib).includes('accordion-content')) return sib;
                        sib = sib.nextElementSibling;
                    }
                }

                // Elementor: matching data-tab
                const tabIndex = triggerEl.getAttribute('data-tab');
                if (tabIndex) {
                    return document.querySelector('[data-tab="' + tabIndex + '"].elementor-tab-content') ||
                           document.querySelector('[data-tab="' + tabIndex + '"].elementor-toggle-content');
                }

                // CSS radio/checkbox label trigger — panel stored directly on element
                if (triggerEl._cssAccordionPanel) return triggerEl._cssAccordionPanel;

                // Next sibling that is a registered panel
                let sib = triggerEl.nextElementSibling;
                while (sib) {
                    if (panelSet.has(sib)) return sib;
                    sib = sib.nextElementSibling;
                }

                // Parent's next sibling
                const parent = triggerEl.parentElement;
                if (parent) {
                    let psib = parent.nextElementSibling;
                    while (psib) {
                        if (panelSet.has(psib)) return psib;
                        psib = psib.nextElementSibling;
                    }
                    // Sibling of parent — check parent's siblings' children
                    for (const child of parent.children) {
                        if (child !== triggerEl && panelSet.has(child)) return child;
                    }
                }

                return null;
            }

            // ════════════════════════════════════════════════════════
            // 5. HELPERS
            // ════════════════════════════════════════════════════════
            function clean(text) {
                return (text || '').replace(/[\t\r\n]+/g, ' ').replace(/  +/g, ' ').trim();
            }

            function forceVisible(el) {
                const saved = [];
                let node = el;
                while (node && node !== document.body) {
                    const s = window.getComputedStyle(node);
                    const isHidden = s.display === 'none' || s.visibility === 'hidden' ||
                                     node.getAttribute('aria-hidden') === 'true';
                    if (isHidden) {
                        saved.push({
                            el: node,
                            display: node.style.display,
                            visibility: node.style.visibility,
                            ariaHidden: node.getAttribute('aria-hidden'),
                        });
                        node.style.display = 'block';
                        node.style.visibility = 'visible';
                        if (node.getAttribute('aria-hidden') === 'true') node.removeAttribute('aria-hidden');
                    }
                    node = node.parentElement;
                }
                return saved;
            }

            function restoreVisible(saved) {
                saved.forEach(({ el, display, visibility, ariaHidden }) => {
                    el.style.display = display;
                    el.style.visibility = visibility;
                    if (ariaHidden !== null) el.setAttribute('aria-hidden', ariaHidden);
                });
            }

            function resolveUrl(el) {
                if (el.href && !el.href.startsWith('javascript')) return el.href;
                const hrefAttr = el.getAttribute('href');
                if (hrefAttr && hrefAttr !== '#' && !hrefAttr.startsWith('javascript')) {
                    try { return new URL(hrefAttr, location.href).href; } catch(e) {}
                }
                const epWrapper = el.getAttribute('data-ep-wrapper-link');
                if (epWrapper) {
                    try {
                        const parsed = JSON.parse(epWrapper.replace(/&quot;/g, '"'));
                        if (parsed.url) return new URL(parsed.url, location.href).href;
                    } catch(e) {}
                }
                for (const attr of ['data-href','data-url','data-link','data-action','data-redirect','data-navigate','data-permalink']) {
                    const v = el.getAttribute(attr);
                    if (v && (v.startsWith('http') || v.startsWith('/'))) {
                        try { return new URL(v, location.href).href; } catch(e) {}
                    }
                }
                const onclick = el.getAttribute('onclick') || '';
                if (onclick) {
                    const p1 = onclick.match(/location\.href\s*=\s*['"]([^'"]+)['"]/);
                    if (p1) { try { return new URL(p1[1], location.href).href; } catch(e) {} }
                    const p2 = onclick.match(/window\.location\s*=\s*['"]([^'"]+)['"]/);
                    if (p2) { try { return new URL(p2[1], location.href).href; } catch(e) {} }
                    const p5 = onclick.match(/['"]((https?:\/\/|\/)[^'"]{3,})['"]/);
                    if (p5) { try { return new URL(p5[1], location.href).href; } catch(e) {} }
                }
                let parent = el.parentElement;
                while (parent && parent !== document.body) {
                    if (parent.tagName === 'A' && parent.href) return parent.href;
                    parent = parent.parentElement;
                }
                return null;
            }

            function getInteractiveType(el) {
                const tag       = el.tagName.toLowerCase();
                const role      = (el.getAttribute('role') || '').toLowerCase();
                const inputType = (el.getAttribute('type') || '').toLowerCase();
                const href      = el.getAttribute('href');

                if (tag === 'a' && href && href !== '#' && !href.startsWith('javascript')) return 'link';
                if (tag === 'button') return 'button';
                if (tag === 'input' && ['button','submit','reset'].includes(inputType)) return 'button';
                if (role === 'button' && !getTriggerType(el)) return 'button';
                if (role === 'link') return 'link';
                if (el.getAttribute('data-ep-wrapper-link')) return 'link';

                if (window.getComputedStyle(el).cursor === 'pointer') {
                    const url = resolveUrl(el);
                    if (url) return 'link';
                    if (el.getAttribute('onclick') || el.getAttribute('data-bs-toggle') ||
                        el.getAttribute('data-toggle') || el.getAttribute('tabindex')) return 'button';
                }
                return null;
            }

            function getInteractiveLabel(el) {
                return clean(
                    el.innerText ||
                    el.textContent ||
                    el.getAttribute('aria-label') ||
                    el.getAttribute('title') ||
                    el.getAttribute('placeholder') ||
                    el.getAttribute('value') ||
                    el.getAttribute('alt') ||
                    ''
                );
            }

            function registerInteractive(el) {
                if (!(el instanceof Element)) return;
                if (isExcluded(el) || !isVisible(el)) return;
                const kind = getTriggerType(el) === 'dropdown' ? 'dropdown' : (getInteractiveType(el) || null);
                if (!kind) return;
                const domPath = buildDomPath(el);
                const nodeId = stableId(`frame-0:${domPath}`);
                if (selectorMap[String(nodeId)]) return;
                selectorMap[String(nodeId)] = {
                    node_id: nodeId,
                    tag: el.tagName.toLowerCase(),
                    kind,
                    label: getInteractiveLabel(el),
                    attributes: getAttributes(el),
                    dom_path: domPath,
                    frame_index: 0,
                    frame_url: window.location.href,
                    parent_id: null,
                    interactive: true,
                    expanded: el.hasAttribute('aria-expanded') ? el.getAttribute('aria-expanded') === 'true' : null,
                    has_popup: cleanAttr(el.getAttribute('aria-haspopup') || '') || null,
                    action_url: resolveUrl(el) || null,
                    is_link: kind === 'link',
                    is_button: kind !== 'link',
                };
            }

            // ════════════════════════════════════════════════════════
            // 6. PANEL CONTENT EXTRACTOR
            // ════════════════════════════════════════════════════════
            const panelProcessed = new Set();

            function extractPanelContent(panelEl, depth) {
                const indent = '  '.repeat(depth);
                const lines  = [];
                const saved  = forceVisible(panelEl);

                function walk(el) {
                    if (panelProcessed.has(el)) return;
                    panelProcessed.add(el);

                    const tag = el.tagName.toLowerCase();
                    const cls = getCls(el);

                    if (['script','style','noscript','meta'].includes(tag)) return;

                    // Nested dropdown inside panel
                    if (getTriggerType(el)) {
                        const text = clean(el.innerText || el.textContent || '');
                        if (text) lines.push(indent + '[DROPDOWN: ' + text + ']');
                        const subPanel = findPanel(el);
                        if (subPanel) {
                            panelProcessed.add(subPanel);
                            subPanel.querySelectorAll('*').forEach(c => panelProcessed.add(c));
                            extractPanelContent(subPanel, depth + 1).forEach(l => lines.push(l));
                        }
                        el.querySelectorAll('*').forEach(c => panelProcessed.add(c));
                        return;
                    }

                    if (['h1','h2','h3','h4','h5','h6'].includes(tag)) {
                        const text = clean(el.innerText || el.textContent);
                        if (text) lines.push(indent + tag.toUpperCase() + ': ' + text);
                        el.querySelectorAll('*').forEach(c => panelProcessed.add(c));
                        return;
                    }

                    if (tag === 'img') {
                        const alt = clean(el.getAttribute('alt') || '');
                        if (alt) lines.push(indent + '[IMAGE: ' + alt + ']');
                        return;
                    }

                    if (tag === 'a') {
                        const href = el.getAttribute('href');
                        const text = clean(el.innerText || el.textContent || '');
                        if (text && href && href !== '#' && !href.startsWith('javascript')) {
                            try { lines.push(indent + text + ' → ' + new URL(href, location.href).href); }
                            catch(e) { lines.push(indent + text); }
                        } else if (text) {
                            lines.push(indent + text);
                        }
                        el.querySelectorAll('*').forEach(c => panelProcessed.add(c));
                        return;
                    }

                    if (tag === 'button' || (tag === 'input' && ['button','submit'].includes((el.getAttribute('type')||'').toLowerCase()))) {
                        const text = clean(el.innerText || el.textContent || el.getAttribute('value') || '');
                        if (text) lines.push(indent + '[BUTTON: ' + text + ']');
                        el.querySelectorAll('*').forEach(c => panelProcessed.add(c));
                        return;
                    }

                    const BLOCK = new Set(['p','li','blockquote','figcaption','td','th','dt','dd','label','caption']);
                    if (BLOCK.has(tag)) {
                        panelProcessed.add(el);

                        function panelInlineText(node) {
                            if (node.nodeType === Node.TEXT_NODE) return clean(node.textContent);
                            if (node.nodeType !== Node.ELEMENT_NODE) return '';
                            const t = node.tagName.toLowerCase();
                            if (['script','style','noscript'].includes(t)) return '';
                            if (t === 'a') return '';
                            return Array.from(node.childNodes).map(panelInlineText).filter(Boolean).join(' ');
                        }

                        const parts = [];
                        el.childNodes.forEach(child => {
                            if (panelProcessed.has(child)) return;
                            if (child.nodeType === Node.TEXT_NODE) {
                                const t = clean(child.textContent);
                                if (t) parts.push({ type: 'text', value: t });
                                return;
                            }
                            if (child.nodeType !== Node.ELEMENT_NODE) return;
                            const ct = child.tagName.toLowerCase();
                            panelProcessed.add(child);
                            child.querySelectorAll('*').forEach(c => panelProcessed.add(c));

                            if (ct === 'a') {
                                const href = child.getAttribute('href');
                                const text = clean(child.innerText || child.textContent || '');
                                if (text && href && href !== '#' && !href.startsWith('javascript')) {
                                    try { parts.push({ type: 'link', text, url: new URL(href, location.href).href }); }
                                    catch(e) { if (text) parts.push({ type: 'text', value: text }); }
                                } else if (text) {
                                    parts.push({ type: 'text', value: text });
                                }
                                return;
                            }

                            const t = panelInlineText(child);
                            if (t) parts.push({ type: 'text', value: t });
                        });

                        let buf = [];
                        function flushBuf() {
                            const m = buf.filter(Boolean).join(' ').trim();
                            if (m) lines.push(indent + m);
                            buf = [];
                        }
                        parts.forEach(part => {
                            if (part.type === 'text') {
                                buf.push(part.value);
                            } else {
                                if (buf.length) {
                                    const pre = buf.filter(Boolean).join(' ').trim();
                                    buf = [];
                                    if (pre) lines.push(indent + pre + ' ' + part.text + ' → ' + part.url);
                                    else lines.push(indent + part.text + ' → ' + part.url);
                                } else {
                                    lines.push(indent + part.text + ' → ' + part.url);
                                }
                            }
                        });
                        flushBuf();
                        return;
                    }

                    el.childNodes.forEach(child => {
                        if (child.nodeType === Node.ELEMENT_NODE) walk(child);
                        else if (child.nodeType === Node.TEXT_NODE) {
                            const text = clean(child.textContent);
                            if (text) lines.push(indent + text);
                        }
                    });
                }

                Array.from(panelEl.childNodes).forEach(child => {
                    if (child.nodeType === Node.ELEMENT_NODE) walk(child);
                    else if (child.nodeType === Node.TEXT_NODE) {
                        const text = clean(child.textContent);
                        if (text) lines.push('  ' + text);
                    }
                });

                restoreVisible(saved);
                return lines;
            }

            // ════════════════════════════════════════════════════════
            // 7. FORM EXTRACTOR
            // ════════════════════════════════════════════════════════
            function extractForm(formEl) {
                const out = ['[FORM START]'];
                formEl.querySelectorAll('input, textarea, select').forEach(field => {
                    const t = (field.getAttribute('type') || 'text').toLowerCase();
                    if (['hidden','submit','button','reset'].includes(t)) return;
                    const id = field.getAttribute('id');
                    const labelEl = id ? document.querySelector('label[for="' + id + '"]') : null;
                    const label =
                        clean(field.getAttribute('placeholder')) ||
                        clean(field.getAttribute('aria-label')) ||
                        (labelEl ? clean(labelEl.innerText) : '') ||
                        field.getAttribute('name') || t;
                    const req = field.hasAttribute('required') ? ' (required)' : '';
                    if (t === 'checkbox') {
                        out.push('  [CHECKBOX: ' + (labelEl ? clean(labelEl.innerText) : label) + req + ']');
                    } else {
                        out.push('  [FIELD: ' + label + req + ']');
                    }
                });
                const sub = formEl.querySelector('button[type="submit"], input[type="submit"], button.elementor-button');
                if (sub) out.push('  [BUTTON: ' + clean(sub.innerText || sub.getAttribute('value') || 'Submit') + ']');
                out.push('[FORM END]');
                return out;
            }

            // ════════════════════════════════════════════════════════
            // 8. MAIN DOM WALKER
            // ════════════════════════════════════════════════════════
            const lines     = [];
            const processed = new Set();

            const SKIP_TAGS    = new Set(['script','style','noscript','meta','link','head']);
            const BLOCK_TAGS   = new Set(['p','li','blockquote','figcaption','td','th','label','dt','dd','caption']);
            const INLINE_TAGS  = new Set(['span','strong','em','b','i','small','mark','del','ins','abbr']);
            const HEADING_TAGS = new Set(['h1','h2','h3','h4','h5','h6']);
            const BLOCK_PARENT = new Set(['p','li','td','th','blockquote','label','figcaption',
                                          'h1','h2','h3','h4','h5','h6']);

            function isVisible(el) {
                // Always pass registered panels through — their content is extracted separately
                if (panelSet.has(el)) return true;
                // Only check CSS display/visibility — do NOT use getBoundingClientRect
                // because domcontentloaded fires before page builder JS (Beaver, Elementor, etc.)
                // has run, so elements may have zero dimensions even though they are visible.
                // Do NOT gate on aria-hidden — accordion triggers use aria-hidden on icon spans
                // inside them, which would cause innerText to return empty for the whole trigger.
                const s = window.getComputedStyle(el);
                if (s.display === 'none' || s.visibility === 'hidden') return false;
                if (parseFloat(s.opacity) === 0) return false;
                return true;
            }

            function processElement(el) {
                if (processed.has(el)) return;
                if (isExcluded(el))    { processed.add(el); return; }
                if (!isVisible(el))    { processed.add(el); return; }

                const tag = el.tagName.toLowerCase();
                const cls = getCls(el);

                if (SKIP_TAGS.has(tag)) { processed.add(el); return; }

                // Forms
                if (tag === 'form') {
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    extractForm(el).forEach(l => lines.push(l));
                    return;
                }

                // Dropdown triggers
                const trigType = getTriggerType(el);
                if (trigType === 'dropdown') {
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                    if (!text) return;
                    lines.push('[DROPDOWN: ' + text + ']');
                    const panel = findPanel(el);
                    if (panel) {
                        processed.add(panel);
                        panel.querySelectorAll('*').forEach(c => processed.add(c));
                        extractPanelContent(panel, 1).forEach(l => lines.push(l));
                    }
                    return;
                }

                // Skip panels in main walk — handled via their trigger
                if (panelSet.has(el)) {
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    return;
                }

                // Non-trigger interactive elements
                const iType = getInteractiveType(el);
                if (iType) {
                    // Before capturing as a single button/link, scan the subtree for
                    // any dropdown triggers (e.g. <label for="X"> inside a cursor:pointer card).
                    // If found, extract them individually first.
                    const nestedTriggers = [];
                    el.querySelectorAll('*').forEach(child => {
                        if (!processed.has(child) && getTriggerType(child) === 'dropdown') {
                            nestedTriggers.push(child);
                        }
                    });

                    if (nestedTriggers.length > 0) {
                        // Don't capture this element as a flat button/link.
                        // Recurse normally so the nested dropdown triggers get processed.
                        el.childNodes.forEach(child => {
                            if (child.nodeType === Node.ELEMENT_NODE) processElement(child);
                            else if (child.nodeType === Node.TEXT_NODE) {
                                const text = clean(child.textContent);
                                if (text) lines.push(text);
                            }
                        });
                        return;
                    }

                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    const text = clean(
                        el.innerText || el.textContent ||
                        el.getAttribute('value') || el.getAttribute('aria-label') ||
                        el.getAttribute('title') || ''
                    );
                    if (!text) return;
                    const url = resolveUrl(el);
                    if (iType === 'button') {
                        lines.push(url ? '[BUTTON: ' + text + '] → ' + url : '[BUTTON: ' + text + ']');
                    } else {
                        lines.push(text + ' → ' + url);
                    }
                    return;
                }

                // Headings — pass through accordion-header wrappers
                if (HEADING_TAGS.has(tag)) {
                    if (hasClass(el, 'accordion-header')) {
                        el.childNodes.forEach(child => {
                            if (child.nodeType === Node.ELEMENT_NODE) processElement(child);
                        });
                        processed.add(el);
                        return;
                    }
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    const text = clean(el.innerText || el.textContent);
                    if (text) lines.push('\n' + tag.toUpperCase() + ': ' + text + '\n');
                    return;
                }

                // HTML5 details
                if (tag === 'details') {
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    const summary = el.querySelector('summary');
                    if (summary) {
                        const summaryText = clean(summary.innerText || summary.textContent || '');
                        if (summaryText) {
                            lines.push('[DROPDOWN: ' + summaryText + ']');
                            extractPanelContent(el, 1).forEach(l => lines.push(l));
                        }
                    }
                    return;
                }

                if (tag === 'img') {
                    processed.add(el);
                    const alt = clean(el.getAttribute('alt') || '');
                    if (alt) lines.push('[IMAGE: ' + alt + ']');
                    return;
                }

                if (tag === 'svg') {
                    processed.add(el);
                    el.querySelectorAll('*').forEach(c => processed.add(c));
                    const title = el.querySelector('title');
                    if (title) {
                        const text = clean(title.textContent);
                        if (text) lines.push('[ICON: ' + text + ']');
                    }
                    return;
                }

                if (BLOCK_TAGS.has(tag)) {
                    // Before treating as plain text block, check if it's a dropdown trigger
                    // e.g. <label for="tab1-485"> controlling a CSS radio accordion panel
                    const blockTrigType = getTriggerType(el);
                    if (blockTrigType === 'dropdown') {
                        processed.add(el);
                        el.querySelectorAll('*').forEach(c => processed.add(c));
                        const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                        if (text) {
                            lines.push('[DROPDOWN: ' + text + ']');
                            const panel = findPanel(el);
                            if (panel) {
                                processed.add(panel);
                                panel.querySelectorAll('*').forEach(c => processed.add(c));
                                extractPanelContent(panel, 1).forEach(l => lines.push(l));
                            }
                        }
                        return;
                    }

                    // Walk children in order, collecting text and handling links inline.
                    // We do NOT just take direct TEXT_NODEs — all text is span-wrapped
                    // on many sites (Squarespace, Wix, etc.) and would be silently lost.
                    processed.add(el);

                    // Helper: recursively get all text from an inline subtree,
                    // stopping at interactive elements (links/buttons handled separately)
                    function inlineText(node) {
                        if (node.nodeType === Node.TEXT_NODE) return clean(node.textContent);
                        if (node.nodeType !== Node.ELEMENT_NODE) return '';
                        const t = node.tagName.toLowerCase();
                        if (['script','style','noscript'].includes(t)) return '';
                        // Don't recurse into links — those are handled separately
                        if (t === 'a') return '';
                        // Don't recurse into interactive elements
                        if (getTriggerType(node) || getInteractiveType(node)) return '';
                        return Array.from(node.childNodes).map(inlineText).filter(Boolean).join(' ');
                    }

                    // Accumulate mixed content: text segments and link segments in order
                    const parts = [];
                    el.childNodes.forEach(child => {
                        if (processed.has(child)) return;

                        if (child.nodeType === Node.TEXT_NODE) {
                            const t = clean(child.textContent);
                            if (t) parts.push({ type: 'text', value: t });
                            return;
                        }

                        if (child.nodeType !== Node.ELEMENT_NODE) return;
                        const ct = child.tagName.toLowerCase();
                        processed.add(child);
                        child.querySelectorAll('*').forEach(c => processed.add(c));

                        // Inline interactive — link
                        if (ct === 'a') {
                            const href = child.getAttribute('href');
                            const text = clean(child.innerText || child.textContent || '');
                            if (text && href && href !== '#' && !href.startsWith('javascript')) {
                                try { parts.push({ type: 'link', text, url: new URL(href, location.href).href }); }
                                catch(e) { if (text) parts.push({ type: 'text', value: text }); }
                            } else if (text) {
                                parts.push({ type: 'text', value: text });
                            }
                            return;
                        }

                        // Block children (nested lists, divs etc) — hand off to main walker
                        if (BLOCK_TAGS.has(ct) || HEADING_TAGS.has(ct)) {
                            processed.delete(child);
                            child.querySelectorAll('*').forEach(c => processed.delete(c));
                            processElement(child);
                            return;
                        }

                        // Inline elements (span, strong, em, etc.) — extract text recursively
                        const t = inlineText(child);
                        if (t) parts.push({ type: 'text', value: t });
                    });

                    // Emit: merge consecutive text parts, emit links on own line
                    let textBuffer = [];
                    function flushBuffer() {
                        const merged = textBuffer.filter(Boolean).join(' ').trim();
                        if (merged) lines.push(merged);
                        textBuffer = [];
                    }
                    parts.forEach(part => {
                        if (part.type === 'text') {
                            textBuffer.push(part.value);
                        } else if (part.type === 'link') {
                            // Flush buffered text first, then emit link
                            // If text was mid-sentence before the link, keep on same line
                            if (textBuffer.length) {
                                const pre = textBuffer.filter(Boolean).join(' ').trim();
                                textBuffer = [];
                                if (pre) lines.push(pre + ' ' + part.text + ' → ' + part.url);
                                else lines.push(part.text + ' → ' + part.url);
                            } else {
                                lines.push(part.text + ' → ' + part.url);
                            }
                        }
                    });
                    flushBuffer();
                    return;
                }

                if (INLINE_TAGS.has(tag)) {
                    // Only emit orphaned inline elements not inside a known block parent
                    const parentTag = (el.parentElement ? el.parentElement.tagName.toLowerCase() : '');
                    if (!BLOCK_PARENT.has(parentTag)) {
                        const text = clean(el.innerText || el.textContent);
                        if (text) lines.push(text);
                        processed.add(el);
                        el.querySelectorAll('*').forEach(c => processed.add(c));
                    } else {
                        processed.add(el);
                    }
                    return;
                }

                // Recurse into everything else
                el.childNodes.forEach(child => {
                    if (child.nodeType === Node.ELEMENT_NODE) {
                        processElement(child);
                    } else if (child.nodeType === Node.TEXT_NODE) {
                        const text = clean(child.textContent);
                        if (text) lines.push(text);
                    }
                });
            }

            Array.from(document.body.children).forEach(child => {
                if (!isExcluded(child)) processElement(child);
            });

            document.querySelectorAll(
                'a[href], button, input, select, textarea, summary, [role="button"], [role="link"], [role="combobox"], [onclick], [data-url], [data-href], [data-link], [data-permalink], [data-job-url], [data-action-url], [data-ep-wrapper-link], [aria-controls], [aria-expanded]'
            ).forEach(registerInteractive);

            const content = lines
                .filter(l => l && l.trim().length > 0)
                .reduce((acc, line) => {
                    if (acc[acc.length - 1] !== line) acc.push(line);
                    return acc;
                }, [])
                .join('\n');

            return {
                page_url: window.location.href,
                content,
                selector_map: selectorMap,
            };
        }
        """
    return js_code
