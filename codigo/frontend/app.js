// Experimento B (Hito 1): matriz digital de seleccion de pictogramas para Picto21.
// Replica en el navegador las reglas de ia_models/juego.py, las pistas ID3 de
// ia_models/id3_pistas.py y el consejero heuristico de ia_models/consejero.py.

const MAX_INTENTOS = 3;
const CARTAS = Object.fromEntries(CATALOGO.cartas.map((c) => [c.id, c]));
const ESC = Object.fromEntries(ESCENARIOS.escenarios.map((e) => [e.id, e]));
const MEJORAS = ESCENARIOS.mejoras;
const PICTO_PREGUNTA = { texto: "¿QUÉ ES?" };

const $ = (id) => document.getElementById(id);
let S = null;

// ------------------------------------------------------------------ utilidades

function normalizar(t) {
  return t.trim().toLowerCase().replace(/ñ/g, "\0")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z\0]/g, "").replace(/\0/g, "ñ");
}
const valor = (p) => [...normalizar(p)].length;
const palabrasValidas = (c) => [c.palabra, ...c.sinonimos];

function letrasElegibles(carta) {
  const maximo = {};
  palabrasValidas(carta).forEach((p) => {
    const cuenta = {};
    [...normalizar(p)].forEach((l) => { cuenta[l] = (cuenta[l] || 0) + 1; });
    Object.entries(cuenta).forEach(([l, n]) => { maximo[l] = Math.max(maximo[l] || 0, n); });
  });
  return barajar(Object.entries(maximo).flatMap(([l, n]) => Array(n).fill(l.toUpperCase())));
}
const urlPicto = (id) => `https://static.arasaac.org/pictograms/${id}/${id}_500.png`;

function barajar(arr) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function decir(texto) {
  if (!("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = "es-PE";
  const voz = speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
  if (voz) u.voice = voz;
  u.rate = 0.85;
  speechSynthesis.speak(u);
}

function imgConRespaldo(id, emoji, clase) {
  const img = document.createElement("img");
  img.alt = "";
  if (id) img.src = urlPicto(id);
  img.onerror = () => {
    const s = document.createElement("span");
    s.className = clase || "emoji";
    s.textContent = emoji;
    img.replaceWith(s);
  };
  if (!id) setTimeout(img.onerror, 0);
  return img;
}

function picto({ texto, arasaac_id, emoji }) {
  const d = document.createElement("div");
  d.className = "picto";
  d.append(imgConRespaldo(arasaac_id, emoji));
  const t = document.createElement("span");
  t.textContent = texto;
  d.append(t);
  return d;
}

const nodoPregunta = document.createElement("div");
nodoPregunta.className = "pregunta-texto";
nodoPregunta.textContent = PICTO_PREGUNTA.texto;

// ------------------------------------------------------------------ pistas ID3

function valorAtributo(c, a) {
  if (a === "primera_letra") return normalizar(c.palabra)[0].toUpperCase();
  if (a === "num_letras") return String(valor(c.palabra));
  return c.atributos[a];
}

function ganancia(cands, a) {
  const n = cands.length;
  if (!n) return 0;
  const grupos = {};
  cands.forEach((c) => { const v = valorAtributo(c, a) ?? "ninguno"; grupos[v] = (grupos[v] || 0) + 1; });
  return Math.log2(n) - Object.values(grupos).reduce((s, k) => s + (k / n) * Math.log2(k), 0);
}

function mejorPista(objetivo, candidatos, usadas) {
  let rest = candidatos;
  usadas.forEach((a) => { rest = rest.filter((c) => valorAtributo(c, a) === valorAtributo(objetivo, a)); });
  const evaluar = (attrs) => attrs
    .filter((a) => !usadas.includes(a) && valorAtributo(objetivo, a) != null)
    .map((a) => [ganancia(rest, a), a]);
  let ops = evaluar(CATALOGO.atributos).filter(([g]) => g > 0);
  if (!ops.length) ops = evaluar(["primera_letra", "num_letras"]);
  if (!ops.length) return null;
  const [g, a] = ops.reduce((m, o) => (o[0] > m[0] + 1e-9 ? o : m));
  const v = valorAtributo(objetivo, a);
  let p = CATALOGO.pictos_pista[v] || { texto: v, emoji: "", arasaac_id: null };
  if (a === "primera_letra") p = { texto: `empieza con ${v}`, emoji: `🔤${v}`, arasaac_id: null };
  if (a === "num_letras") p = { texto: `${v} letras`, emoji: `🔢${v}`, arasaac_id: null };
  return { atributo: a, ganancia: g, ...p };
}

// ------------------------------------------------------------------ consejero

function valorConMejora(base, m) {
  if (m === "mas_uno") return base + 1;
  if (m === "menos_uno") return Math.max(1, base - 1);
  return base;
}

function sugerir() {
  if (S.fase !== "decidir") return null;
  const suma = S.suma, visible = valor(CARTAS[S.crupier.visible].palabra), faltan = 21 - suma;
  const puedePedir = S.mazo.length > 0;
  if (S.mejora && !S.mejoraActiva && puedePedir && suma < 18) {
    if (S.mejora === "escudo" && suma > 13) return ["mejora", "Activa el escudo antes de arriesgarte."];
    if (S.mejora === "menos_uno" && suma > 15 && suma < 18) return ["mejora", "Usa menos uno para la próxima carta."];
    if (S.mejora === "mas_uno" && faltan >= 10) return ["mejora", "Usa más uno, estás lejos de veintiuno."];
  }
  if (!puedePedir) return ["parar", "Ya no hay cartas."];
  if (S.mejoraActiva === "escudo") return ["pedir", "El escudo te protege si te pasas."];
  if (S.mejoraActiva === "menos_uno" && suma < 18) return ["pedir", "La próxima carta vale uno menos."];
  if (suma <= 15) return ["pedir", `Te faltan ${faltan}. Pide otra carta.`];
  if (suma >= 18) return ["parar", `Tienes ${suma}. Mejor para.`];
  if (visible >= 6) return ["pedir", `El crupier muestra ${visible}. Arriesga una carta.`];
  return ["parar", `El crupier muestra ${visible}. Mejor para.`];
}

function puntajeDe(palabra, mejora) {
  const ajuste = mejora === "mas_uno" || mejora === "menos_uno" ? mejora : null;
  return valorConMejora(valor(palabra), ajuste);
}

function palabraQueHabriaSalvado(carta, dicha, sumaAntes, mejora, sirve) {
  const dichaN = normalizar(dicha);
  let mejor = null;
  palabrasValidas(carta).map(normalizar).forEach((p) => {
    if (p === dichaN) return;
    const suma = sumaAntes + puntajeDe(p, mejora);
    if (!sirve(suma)) return;
    if (!mejor || suma > mejor.suma) mejor = { palabra: p, suma };
  });
  return mejor;
}

// ------------------------------------------------------------------ reglas

function nuevaRonda() {
  const overlay = $("fin-overlay");
  overlay.classList.add("hidden");
  overlay.setAttribute("aria-hidden", "true");
  const esc = ESC[$("sel-escenario").value];
  const mazo = barajar(Array(esc.copias).fill(esc.mazo).flat());
  const visible = mazo.shift();
  S = {
    esc, mazo, mano: [], suma: 0, fase: "decidir",
    crupier: { visible, mano: [visible], suma: valor(CARTAS[visible].palabra) },
    mejora: esc.mejoras_disponibles.length ? esc.mejoras_disponibles[Math.floor(Math.random() * esc.mejoras_disponibles.length)] : null,
    mejoraActiva: null, carta: null, intentos: 0, pistas: [], nivel: Number($("sel-nivel").value),
    candidatos: [...new Set(esc.mazo)].map((id) => CARTAS[id]),
    opciones: [], erradas: [],
  };
  mensaje("", "");
  render();
  decir("¿Pides carta o paras?");
}

function sacarCarta() {
  S.carta = CARTAS[S.mazo.shift()];
  S.intentos = 0;
  S.pistas = [];
  S.fase = "reconocer";
  const distractor = barajar(S.candidatos.filter((c) => c.id !== S.carta.id))[0];
  S.opciones = barajar([S.carta, distractor].filter(Boolean));
  S.erradas = [];
  mensaje("", "");
  render();
  decir(S.nivel === 1 ? "Elige una carta" : "¿Qué es?");
}

function responder(texto) {
  if (S.fase !== "reconocer") return;
  const carta = S.carta;
  const coincide = palabrasValidas(carta).map(normalizar).find((p) => p === normalizar(texto));
  if (coincide) {
    aceptarPalabra(coincide);
  } else {
    S.intentos++;
    if (S.intentos >= MAX_INTENTOS) {
      mensaje(`Es ${carta.palabra.toUpperCase()}`, "mal");
      decir(`Es ${carta.palabra}. ¡Sigamos!`);
      agregarCarta(carta.palabra);
    } else {
      S.erradas = S.erradas || [];
      const clickeada = S.opciones?.find((c) => palabrasValidas(c).some((p) => normalizar(p) === normalizar(texto)));
      if (clickeada && !S.erradas.includes(clickeada.id)) S.erradas.push(clickeada.id);
      const p = mejorPista(carta, S.candidatos, S.pistas.map((x) => x.atributo));
      if (p) S.pistas.push(p);
      mensaje("Intenta otra vez", "mal");
      decir(`Intenta otra vez. Pista: ${S.pistas.map((x) => x.texto).join(", ")}`);
    }
  }
  render();
}

function aceptarPalabra(palabra) {
  agregarCarta(palabra);
  if (S.fase !== "fin") {
    mensaje(`¡Muy bien! ${palabra.toUpperCase()} vale ${valor(palabra)}`, "bien");
    decir(`¡Muy bien! ${palabra}. Vale ${valor(palabra)}.`);
  }
  render();
}

function agregarCarta(palabra) {
  const mejora = S.mejoraActiva === "mas_uno" || S.mejoraActiva === "menos_uno" ? S.mejoraActiva : null;
  const sumaAntes = S.suma;
  const v = puntajeDe(palabra, mejora);
  if (mejora) S.mejoraActiva = null;
  S.mano.push({ carta: S.carta, palabra, v, sumaAntes, mejora });
  S.suma += v;
  S.fase = "decidir";
  if (S.suma > 21) {
    if (S.mejoraActiva === "escudo") {
      const q = S.mano.pop();
      S.suma -= q.v;
      S.mejoraActiva = null;
      setTimeout(() => decir("¡El escudo te salvó!"), 1500);
    } else {
      const alt = palabraQueHabriaSalvado(S.carta, palabra, sumaAntes, mejora, (s) => s <= 21);
      terminar("se_paso", alt);
    }
  } else if (S.suma === 21) {
    jugarCrupier();
  }
}

function jugarCrupier() {
  while (S.crupier.suma < 17 && S.mazo.length) {
    const c = S.mazo.shift();
    S.crupier.mano.push(c);
    S.crupier.suma += valor(CARTAS[c].palabra);
  }
  const j = S.suma, c = S.crupier.suma;
  const res = c > 21 || j > c ? "gana" : j === c ? "empate" : "pierde";
  let alt = null;
  if (res === "pierde" && S.mano.length) {
    const ult = S.mano.at(-1);
    alt = palabraQueHabriaSalvado(ult.carta, ult.palabra, ult.sumaAntes, ult.mejora, (s) => s <= 21 && s > c);
  }
  terminar(res, alt);
}

function terminar(res, alt) {
  S.fase = "fin";
  const textos = {
    gana: ["¡GANASTE!", "¡Ganaste! Muy bien."],
    empate: ["EMPATE", "Empate."],
    pierde: ["GANA EL CRUPIER", "Gana el crupier."],
    se_paso: ["TE PASASTE DE 21", "Te pasaste de veintiuno."],
  };
  let texto = textos[res][0];
  let voz = textos[res][1];
  if (alt) {
    const nota = `Pudiste decir ${alt.palabra.toUpperCase()} y quedar en ${alt.suma}. La próxima vez.`;
    texto = `${texto}. ${nota}`;
    voz = `${voz} ${nota}`;
  }
  mensaje(texto, res === "gana" ? "bien" : "mal");

  const overlay = $("fin-overlay");
  const titulo = $("fin-titulo");
  const detalle = $("fin-mensaje");
  const mensajes = {
    gana: ["¡Felicidades!", "¡Ganaste el juego!"],
    empate: ["¡Empataste!", "No pasa nada, ¡otra vuelta y lo intentamos de nuevo!"],
    pierde: ["¡Otra vez será!", "No te preocupes, ¡la próxima partida puede salir mejor!"],
    se_paso: ["¡Casi lo logras!", "Te pasaste un poquito, pero aún puedes volver a jugar y probar otra vez."],
  };
  titulo.textContent = mensajes[res][0];
  detalle.textContent = alt ? `Pudiste decir ${alt.palabra.toUpperCase()} y quedarse en ${alt.suma}.` : mensajes[res][1];
  overlay.classList.remove("hidden");
  overlay.setAttribute("aria-hidden", "false");
  renderAbanico();
  overlay.classList.toggle("victoria", res === "gana");

  setTimeout(() => decir(voz), 400);
}

function renderAbanico() {
  const caja = $("fin-abanico");
  if (!caja || !S?.mano.length) {
    if (caja) caja.replaceChildren();
    return;
  }
  const n = S.mano.length;
  caja.replaceChildren(...S.mano.map((m, i) => {
    const d = document.createElement("div");
    d.className = "carta-fan";
    const offset = i - (n - 1) / 2;
    const giro = n === 1 ? 0 : offset * 14;
    const spread = n === 1 ? 0 : offset * 58;
    d.style.setProperty("--giro", `${giro}deg`);
    d.style.setProperty("--desplaza", `${spread}px`);
    d.style.setProperty("--i", String(i));
    const cabeza = document.createElement("div");
    cabeza.className = "carta-fan-cabeza";
    const nombre = document.createElement("span");
    nombre.className = "carta-fan-nombre";
    nombre.textContent = m.carta.palabra.toUpperCase();
    const valorEl = document.createElement("span");
    valorEl.className = "carta-fan-valor";
    valorEl.textContent = m.v;
    cabeza.append(nombre, valorEl);
    d.append(cabeza, imgConRespaldo(m.carta.arasaac_id, m.carta.emoji));
    d.style.zIndex = String(Math.round(n - Math.abs(i - (n - 1) / 2)));
    return d;
  }));
}

function mensaje(t, clase) { const m = $("mensaje"); m.textContent = t; m.className = `mensaje ${clase}`; }

// ------------------------------------------------------------------ interfaz

function render() {
  $("suma-jugador").textContent = S.suma;
  $("suma-crupier").textContent = S.fase === "fin" ? S.crupier.suma : valor(CARTAS[S.crupier.visible].palabra);
  renderMano($("mano-jugador"), S.mano.map((m) => ({ c: m.carta, v: m.v })));
  const manoC = S.fase === "fin" ? S.crupier.mano : [S.crupier.visible];
  renderMano($("mano-crupier"), manoC.map((id) => ({ c: CARTAS[id], v: valor(CARTAS[id].palabra) })));

  const mesa = document.querySelector(".mesa");
  const reconocer = S.fase === "reconocer";
  const decidir = S.fase === "decidir";
  mesa.classList.toggle("modo-reconocer", reconocer);
  mesa.classList.toggle("modo-decidir", decidir);
  mesa.classList.toggle("modo-fin", S.fase === "fin");
  mesa.classList.toggle("nivel-1", reconocer && S.nivel === 1);
  const mostrandoCarta = reconocer && S.nivel !== 1;
  nodoPregunta.textContent = S.nivel === 1 ? "Elige una carta" : PICTO_PREGUNTA.texto;
  $("pregunta").replaceChildren(...(reconocer ? [nodoPregunta] : []));
  const tituloEleccion = $("titulo-eleccion");
  if (tituloEleccion) tituloEleccion.hidden = true;
  const intentos = $("intentos");
  intentos.hidden = !reconocer;
  intentos.textContent = reconocer ? `Intento ${Math.min(S.intentos + 1, MAX_INTENTOS)} de ${MAX_INTENTOS}` : "";
  const img = $("carta-img"), em = $("carta-emoji");
  const cartaMostrada = mostrandoCarta ? S.carta : null;
  if (cartaMostrada && img.dataset.carta !== cartaMostrada.id) {
    const carta = $("carta");
    carta.classList.remove("carta-entra");
    void carta.offsetWidth;
    carta.classList.add("carta-entra");
    img.dataset.carta = cartaMostrada.id;
    em.textContent = cartaMostrada.emoji;
    img.hidden = false; em.hidden = true;
    img.onerror = () => { img.hidden = true; em.hidden = false; };
    img.removeAttribute("src");
    img.src = urlPicto(cartaMostrada.arasaac_id);
  } else if (!cartaMostrada) {
    img.dataset.carta = "";
  }
  $("pistas").replaceChildren(...(reconocer ? S.pistas.map(picto) : []));
  renderRespuesta(reconocer);

  $("btn-pedir").disabled = !decidir || !S.mazo.length;
  $("btn-parar").disabled = !decidir || !S.mano.length;
  $("btn-mejora").disabled = !decidir || !S.mejora || !!S.mejoraActiva;
  const m = S.mejoraActiva || S.mejora;
  $("mejora-emoji").textContent = m ? MEJORAS[m].emoji : "—";
  $("mejora-texto").textContent = S.mejoraActiva ? `${MEJORAS[m].texto} ACTIVA` : m ? MEJORAS[m].texto : "SIN MEJORA";

  document.querySelectorAll(".btn-accion").forEach((b) => b.classList.remove("sugerida"));
  const sug = sugerir();
  if (sug) {
    $(`btn-${sug[0]}`).classList.add("sugerida");
    $("consejo").textContent = `Consejo: ${sug[1]}`;
  } else {
    $("consejo").textContent = "";
  }
}

function renderMano(cont, cartas) {
  cont.replaceChildren(...cartas.map(({ c, v }) => {
    const d = document.createElement("div");
    d.append(imgConRespaldo(c.arasaac_id, c.emoji, "mini-emoji"));
    const s = document.createElement("span");
    s.className = "valor";
    s.textContent = v;
    d.append(s);
    return d;
  }));
}

function renderRespuesta(activo) {
  const r = $("respuesta");
  r.replaceChildren();
  r.classList.remove("opciones-cartas");
  if (!activo) return;

  if (S.nivel === 1) {
    r.classList.add("opciones-cartas");
    (S.opciones || []).forEach((carta) => {
      const b = document.createElement("button");
      b.className = "carta-opcion";
      b.type = "button";
      if (S.erradas?.includes(carta.id)) b.classList.add("errada");
      const cabeza = document.createElement("div");
      cabeza.className = "carta-opcion-cabeza";
      const nombre = document.createElement("span");
      nombre.className = "carta-opcion-nombre";
      nombre.textContent = carta.palabra.toUpperCase();
      const valorEl = document.createElement("span");
      valorEl.className = "carta-opcion-valor";
      valorEl.textContent = carta.valor ?? valor(carta.palabra);
      cabeza.append(nombre, valorEl);
      b.append(cabeza, imgConRespaldo(carta.arasaac_id, carta.emoji));
      b.onclick = () => {
        if (b.classList.contains("errada")) return;
        S.carta = carta;
        aceptarPalabra(carta.palabra);
      };
      b.onmouseenter = b.onfocus = () => decir(carta.palabra);
      r.append(b);
    });
  } else if (S.nivel === 2) {
    r.classList.remove("opciones-cartas");
    const armada = document.createElement("div");
    armada.className = "palabra-armada";
    let texto = "";
    const validas = palabrasValidas(S.carta).map(normalizar);
    const puedeCrecer = (t) => validas.some((p) => p !== t && p.startsWith(t));
    const ok = document.createElement("button");
    ok.className = "btn-control ok";
    const okIcon = document.createElement("img");
    okIcon.src = "./assets/keyboard/keyboard_enter.svg";
    okIcon.alt = "Aceptar";
    ok.appendChild(okIcon);
    ok.disabled = true;
    const refrescar = () => {
      armada.textContent = texto;
      const n = normalizar(texto);
      ok.disabled = !validas.includes(n);
      if (validas.includes(n) && !puedeCrecer(n)) responder(texto);
    };
    const fichas = letrasElegibles(S.carta).map((l) => {
      const b = document.createElement("button");
      b.className = "ficha";
      const icon = document.createElement("img");
      icon.src = `./assets/keyboard/keyboard_${l.toLowerCase()}.svg`;
      icon.alt = l;
      b.appendChild(icon);
      b.onclick = () => {
        texto += l; b.classList.add("usada"); decir(l); refrescar();
      };
      return b;
    });
    const borrar = document.createElement("button");
    borrar.className = "btn-control borrar";
    const borrarIcon = document.createElement("img");
    borrarIcon.src = "./assets/keyboard/keyboard_backspace_icon.svg";
    borrarIcon.alt = "Borrar";
    borrar.appendChild(borrarIcon);
    borrar.onclick = () => {
      texto = "";
      fichas.forEach((f) => f.classList.remove("usada"));
      refrescar();
    };
    ok.onclick = () => { if (validas.includes(normalizar(texto))) responder(texto); };
    r.append(armada, ...fichas, ok, borrar);
  } else {
    r.classList.remove("opciones-cartas");
    const inp = document.createElement("input");
    inp.className = "entrada";
    inp.autocomplete = "off";
    inp.setAttribute("aria-label", "Escribe la palabra");
    const ok = document.createElement("button");
    ok.className = "btn-control ok";
    ok.textContent = "✔";
    const enviar = () => { if (inp.value.trim()) responder(inp.value); };
    ok.onclick = enviar;
    inp.onkeydown = (e) => { if (e.key === "Enter") enviar(); };
    r.append(inp, ok);
    setTimeout(() => inp.focus(), 0);
  }
}

// ------------------------------------------------------------------ eventos

function init() {
  const sel = $("sel-escenario");
  ESCENARIOS.escenarios.forEach((e) => sel.add(new Option(e.nombre, e.id)));
  sel.onchange = () => { $("sel-nivel").value = ESC[sel.value].nivel_inicial; nuevaRonda(); };
  $("sel-nivel").value = ESC[sel.value].nivel_inicial;
  $("sel-nivel").onchange = () => { S.nivel = Number($("sel-nivel").value); render(); };
  $("btn-nueva").onclick = nuevaRonda;
  $("btn-volver-jugar").onclick = nuevaRonda;
  $("btn-pedir").onclick = () => { if (S.fase === "decidir" && S.mazo.length) sacarCarta(); };
  $("btn-parar").onclick = () => { if (S.fase === "decidir") { mensaje("", ""); jugarCrupier(); render(); } };
  $("btn-mejora").onclick = () => {
    if (S.fase !== "decidir" || !S.mejora) return;
    S.mejoraActiva = S.mejora; S.mejora = null;
    decir(MEJORAS[S.mejoraActiva].descripcion);
    render();
  };
  $("btn-audio").onclick = () => {
    if (S.fase === "reconocer") {
      const base = S.nivel === 1 ? "Elige una carta" : "¿Qué es?";
      decir(S.pistas.length ? `${base}. Pista: ${S.pistas.map((p) => p.texto).join(", ")}` : base);
    } else if (S.fase === "decidir" && !S.mano.length) {
      decir("¿Pides carta o paras?");
    } else {
      decir(`Tienes ${S.suma}. ${$("consejo").textContent}`);
    }
  };
  nuevaRonda();
}

init();
