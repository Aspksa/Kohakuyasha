(() => {
  "use strict";
  const Koh = window.Koh; if (!Koh || !Koh.registerTab) return;
  const {el, ui} = Koh;
  const EDIT_SIZE = 200;

  Koh.registerTab("avatar", "Аватар", () => {
    const a = Koh.settings.avatar, nodes = [];
    const save = Koh.debounce(async () => { try { Object.assign(Koh.settings.avatar, await Koh.api("/api/settings/avatar", {method: "PUT", body: JSON.stringify(Koh.settings.avatar)})); } catch { Koh.toast("Не удалось сохранить настройки аватара"); } }, 350);
    const prev = el("div", "preview"), pv = el("div", "avatar"), pimg = el("img"); pimg.alt = ""; pimg.draggable = false; pv.append(pimg, el("span", "avatar-dot")); prev.append(pv);
    const refresh = () => { Koh.applyAvatar(pv, pimg); };
    const change = (patch) => { Object.assign(Koh.settings.avatar, patch); refresh(); Koh.notify(); save(); };
    refresh(); nodes.push(prev);

    // ----- faces gallery + editor -----
    const facesSec = ui.section("ЛИЦА · показываются везде: аватар, чат, кабинет, меню"), gallery = el("div", "faces"), editorBox = el("div");
    const fileInput = el("input"); fileInput.type = "file"; fileInput.accept = "image/png,image/jpeg,image/webp,image/gif"; fileInput.hidden = true;
    function drawFaces() {
      gallery.replaceChildren();
      Koh.settings.faces.forEach(f => {
        const t = el("div", "face" + (f.id === Koh.settings.avatar.active_face ? " on" : "")); t.tabIndex = 0; t.setAttribute("role", "button"); t.title = f.name;
        const im = el("img"); im.src = f.small; im.alt = f.name; im.draggable = false; t.append(im);
        const pick = () => { change({active_face: f.id}); drawFaces(); };
        t.addEventListener("click", pick); t.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        if (!f.builtin) {
          const fx = el("div", "fx"), edit = el("button", "", "✎"), del = el("button", "", "×");
          edit.type = del.type = "button"; edit.title = "Кадрировать"; del.title = "Удалить";
          edit.addEventListener("click", (e) => { e.stopPropagation(); openEditor(f.id); });
          del.addEventListener("click", async (e) => {
            e.stopPropagation(); if (!confirm("Удалить это лицо?")) return;
            try { Koh.setAll(await Koh.api(`/api/avatar/faces/${f.id}`, {method: "DELETE"})); editorBox.replaceChildren(); drawFaces(); refresh(); } catch { Koh.toast("Не удалось удалить лицо"); }
          });
          fx.append(edit, del); t.append(fx);
        }
        gallery.append(t);
      });
      const add = el("button", "face face-add", "+"); add.type = "button"; add.title = "Загрузить своё лицо"; add.addEventListener("click", () => fileInput.click());
      gallery.append(add);
    }
    fileInput.addEventListener("change", async () => {
      const f = fileInput.files[0]; fileInput.value = ""; if (!f) return;
      if (f.size > 6_000_000) { Koh.toast("Файл больше 6 МБ"); return; }
      try {
        const r = await Koh.api("/api/avatar/faces", {method: "POST", body: JSON.stringify({name: f.name.replace(/\.[^.]+$/, ""), data: await Koh.fileToBase64(f)})});
        Koh.setAll(r.settings); change({active_face: r.id}); drawFaces(); openEditor(r.id); Koh.toast("Лицо загружено: подберите кадр");
      } catch (e) { Koh.toast(e.message || "Не удалось загрузить изображение"); }
    });
    function openEditor(id) {
      const face = Koh.settings.faces.find(f => f.id === id); if (!face) return;
      const st = {zoom: face.zoom || 1, x: face.x || 0, y: face.y || 0}, box = el("div", "editor");
      const crop = el("div", "crop"), cimg = el("img"); cimg.alt = ""; cimg.src = face.full; crop.append(cimg);
      const place = () => {
        const w = face.w || 1, h = face.h || 1, side = Math.min(w, h) / st.zoom, left = (w - side) / 2 + st.x * (w - side) / 2, top = (h - side) / 2 + st.y * (h - side) / 2, k = EDIT_SIZE / side;
        cimg.style.width = w * k + "px"; cimg.style.height = h * k + "px"; cimg.style.left = -left * k + "px"; cimg.style.top = -top * k + "px";
      };
      const side = el("div"), name = el("input"); name.type = "text"; name.value = face.name; name.maxLength = 60;
      side.append(ui.field("Название", name),
        ui.range("", 1, 4, 0.05, st.zoom, v => `Масштаб: ${v.toFixed(2)}×`, v => { st.zoom = v; place(); }),
        ui.range("", -1, 1, 0.02, st.x, v => `Сдвиг по горизонтали: ${Math.round(v * 100)}`, v => { st.x = v; place(); }),
        ui.range("", -1, 1, 0.02, st.y, v => `Сдвиг по вертикали: ${Math.round(v * 100)}`, v => { st.y = v; place(); }));
      const acts = el("div", "actions");
      acts.append(ui.btn("Применить", "primary", async () => {
        try { Koh.setAll(await Koh.api(`/api/avatar/faces/${id}`, {method: "PUT", body: JSON.stringify({...st, name: name.value})})); editorBox.replaceChildren(); drawFaces(); refresh(); Koh.toast("Кадр сохранён"); }
        catch (e) { Koh.toast(e.message || "Не удалось сохранить кадр"); }
      }), ui.btn("Отмена", "", () => editorBox.replaceChildren()));
      side.append(acts); box.append(crop, side); editorBox.replaceChildren(box); place();
    }
    drawFaces(); facesSec.append(gallery, fileInput, editorBox, el("p", "hint", "PNG, JPEG, WebP или GIF до 6 МБ. Загруженное изображение перекодируется на сервере; можно хранить до 12 лиц."));
    facesSec.append(ui.toggle("Заменять логотип лицом", a.replace_logo, v => change({replace_logo: v}), "В меню слева и на странице «Обзор»"));
    nodes.push(facesSec);

    // ----- look -----
    const look = ui.section("ВИД");
    look.append(ui.field("Что показывать", ui.seg([["face", "Только лицо"], ["full", "Вся картинка"]], a.crop, v => change({crop: v}))));
    look.append(ui.field("Форма", ui.seg([["soft", "Мягкие края"], ["rounded", "Скруглённый"], ["circle", "Круг"]], a.shape, v => change({shape: v}))));
    look.append(ui.range("", 48, 240, 4, a.size, v => `Размер: ${v} px`, v => change({size: v})));
    look.append(ui.range("", 30, 100, 5, a.opacity, v => `Прозрачность: ${v}%`, v => change({opacity: v})));
    const colorToggle = (label, flag, colorKey) => {
      const wrap = el("div"), c = el("input"); c.type = "color"; c.value = a[colorKey]; c.title = "Цвет"; c.addEventListener("input", () => change({[colorKey]: c.value}));
      const row = ui.toggle(label, a[flag], v => change({[flag]: v})); const cr = el("div", "color-row"); cr.append(el("span", "hint", "Цвет:"), c); wrap.append(row, cr); return wrap;
    };
    look.append(colorToggle("Рамка", "ring", "ring_color"), colorToggle("Свечение", "glow", "glow_color"), ui.toggle("Индикатор статуса", a.status_dot, v => change({status_dot: v})));
    nodes.push(look);

    // ----- behaviour -----
    const beh = ui.section("ПОВЕДЕНИЕ");
    beh.append(ui.field("Анимация", ui.seg([["none", "Нет"], ["float", "Парение"], ["pulse", "Пульс"], ["breathe", "Дыхание"]], a.animation, v => change({animation: v}))));
    const actions = [["chat", "Чат"], ["cabinet", "Кабинет"], ["none", "Ничего"]];
    beh.append(ui.field("Левый клик", ui.seg(actions, a.left_action, v => change({left_action: v}))));
    beh.append(ui.field("Правый клик (на сенсорном экране — долгое нажатие)", ui.seg(actions, a.right_action, v => change({right_action: v}))));
    beh.append(ui.toggle("Прилипать к краю экрана", a.snap_edges, v => change({snap_edges: v}), "После перетаскивания аватар уходит к ближайшему краю"));
    beh.append(ui.toggle("Приглушать при бездействии", a.idle_dim, v => change({idle_dim: v}), "Становится полупрозрачным через 12 секунд"));
    beh.append(ui.toggle("Скрывать, пока открыто окно", a.hide_on_open, v => change({hide_on_open: v})));
    beh.append(ui.toggle("Приветствие при открытии", a.greeting, v => change({greeting: v}), "Короткая реплика по времени суток"));
    nodes.push(beh);
    const acts = el("div", "actions"); acts.append(ui.btn("Вернуть в правый нижний угол", "", () => Koh.resetPos())); nodes.push(acts);
    nodes.push(el("p", "hint", "Аватар можно перетаскивать по любой странице. Размер и положение окон кабинета и чата меняются за рамку или заголовок."));
    return nodes;
  }, 20);
})();
