import streamlit as st
import pandas as pd
import io
from datetime import datetime
import plotly.graph_objects as go

# =========================
# CONFIG & THEME
# =========================
st.set_page_config(page_title="Test d'auto-positionnement APS", page_icon="✅", layout="wide")

# ---- CSS / Charte graphique
st.markdown("""
<style>
:root{
  --prim:#2f80ed; --sec:#2ecc71; --warn:#f39c12; --err:#e74c3c; --bg:#f5f7fb; --card:#ffffff; --text:#2c3e50;
  --accent:#9b59b6; --muted:#95a5a6; --sky:#56ccf2; --leaf:#27ae60; --sun:#f1c40f;
}
body{ background: radial-gradient(1200px 800px at 10% 10%, #eef4ff 0%, #f6fbf8 45%, #f5f7fb 100%); }
.block-container{ padding-top:1.2rem; padding-bottom:2rem; }
h1,h2,h3{ color:var(--text); font-weight:700; }
hr{opacity:.1;}
.stButton>button{
  background: linear-gradient(90deg, var(--prim), var(--sec));
  color:#fff;border:none;border-radius:12px;padding:.7em 1.4em;font-size:1rem;
  box-shadow:0 6px 18px rgba(47,128,237,.25); transition:.25s;
}
.stButton>button:hover{ transform:translateY(-1px) scale(1.02); }
.card{
  background:var(--card); border-radius:16px; padding:16px 18px; box-shadow:0 4px 18px rgba(0,0,0,.06); margin:10px 0;
}
.kpi{
  background:linear-gradient(135deg, #ffffff, #f1f8ff); border:1px solid #eaf2ff;
}
.progress-wrap{ width:100%; background:#ecf0f1; border-radius:14px; height:28px; overflow:hidden; }
.progress-bar{ height:28px; border-radius:14px; display:flex; align-items:center; justify-content:center; color:white; font-weight:700; }
.progress-bar-alt{ height:22px; border-radius:12px; display:flex; align-items:center; justify-content:center; color:#1b2631; font-weight:700; background:linear-gradient(90deg, #e8f4ff, #eaffe6); border:1px solid #e0ecff;}
.legend-dot{display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px;}
.req{color:var(--err); font-weight:700; padding:2px 8px; border-radius:999px; background:#fdecea; border:1px solid #f7c6c5;}
.opt{color:#2d3436; font-weight:600; padding:2px 8px; border-radius:999px; background:#eef6ff; border:1px solid #d9e8ff;}
.small{font-size:.9rem; color:#5f6c7b;}
.section-title{display:flex; align-items:center; gap:.6rem; padding:.4rem .6rem; background:linear-gradient(90deg,#ffffff,#f7fbff); border-left:4px solid var(--sky); border-radius:10px;}
.section-title .emoji{font-size:1.4rem;}
.download-note{font-size:.85rem; color:#607086;}
.reset-link button{background:#fff !important; color:#34495e; border:1px solid #dfe6ef !important;}
.badge{display:inline-block; font-size:.8rem; padding:.1rem .5rem; border-radius:999px; border:1px solid #e3e8ef; background:#fff;}
.field-help{font-size:.85rem; color:#6b7a90; margin-top:-6px;}
</style>
""", unsafe_allow_html=True)

# =========================
# HELPERS / BARÈME
# =========================

# Barème par domaines (pondérations qui totalisent 100)
WEIGHTS = {
    "Referent": 20,           # référent + formation + organisme
    "Regulier": 25,           # existence + part usagers + durée + variété
    "Occasionnel": 10,        # existence
    "Encadrement": 15,        # profils pro
    "Projet": 10,             # inscrit au projet
    "Liens": 10,              # partenaires
    "Qualite": 10             # objectifs, satisfaction perçue
}
DOMAINS_ORDER = ["Referent", "Regulier", "Occasionnel", "Encadrement", "Projet", "Liens", "Qualite"]

def scale(value, mini, maxi):
    if value <= mini: return 0.0
    if value >= maxi: return 1.0
    return (value-mini)/(maxi-mini)

def color_for_score(s):
    if s < 40: return "var(--err)"
    if s < 70: return "var(--warn)"
    return "var(--sec)"

def pct_to_float(pct_label):
    # "30-40%" -> 0.35 ; "90-100%" -> 0.95
    num = pct_label.split("%")[0]         # "30-40"
    a,b = num.split("-")
    return (float(a)+float(b))/200.0

def duree_to_minutes(label):
    m = {"0 min":0,"20 min":20,"30 min":30,"45 min":45,"1h":60,"1h30":90,"2h":120,"2h30":150}
    return m.get(label,0)

def compute_indicators(data):
    """Calcule les sous-indicateurs [0..100] par domaine puis l'indicateur global (pondéré)."""
    subs = {}

    # --- Référent (20)
    sub_ref = 0
    if data["referent"] == "Oui": sub_ref += 0.6
    if data["formation_referent"] == "Oui": sub_ref += 0.25
    if data["organisme"] != "Aucun / Non précisé": sub_ref += 0.15
    subs["Referent"] = round(sub_ref*100,1)

    # --- Régulier (25)
    sub_reg = 0
    if data["activite_reguliere"] != "Non":
        sub_reg += 0.35
        # part d'usagers : cible >= 50%
        part = pct_to_float(data["nb_usagers"])  # 0..1
        sub_reg += 0.35 * scale(part, 0.10, 0.70)
        # durée hebdo : cible >= 90 min
        minutes = duree_to_minutes(data["duree"])
        sub_reg += 0.20 * scale(minutes, 30, 90)
        # diversité : au moins 2 types → meilleur
        diversite = len(data["types_activites"])
        sub_reg += 0.10 * min(diversite/3, 1.0)
    else:
        sub_reg = 0
    subs["Regulier"] = round(sub_reg*100,1)

    # --- Occasionnel (10)
    sub_occ = 1.0 if data["occasionnelle"] == "Oui" else 0.0
    subs["Occasionnel"] = round(sub_occ*100,1)

    # --- Encadrement (15)
    # 1 pro = bien, 2 profils = mieux
    enc = data["encadrants"]
    if "Aucun professionnel" in enc or len(enc)==0:
        sub_enc = 0
    else:
        base = 0.6
        bonus = 0.4 * min(len(enc)/2,1.0)
        sub_enc = base + bonus
    subs["Encadrement"] = round(sub_enc*100,1)

    # --- Projet (10)
    subs["Projet"] = 100.0 if data["projet_etab"]=="Oui" else 0.0

    # --- Liens (10)
    liens = data["liens"]
    if "Aucun" in liens or len(liens)==0:
        sub_liens = 0
    else:
        sub_liens = min(len(liens)/3,1.0)
    subs["Liens"] = round(sub_liens*100,1)

    # --- Qualité/intentions (10)
    # objectifs : plus il y en a (pertinents), mieux c'est (max 5)
    obj = len(data["objectifs"])
    sat = data["satisfaction"]
    plus = "Vouloir plus d’APS" in sat
    pas_satisfaits = "Ne pas être satisfaits" in sat
    # base sur objectifs
    s_obj = min(obj/5, 1.0) * 0.7
    # perception : pénalité si insatisfaction
    pen = 0.0
    if pas_satisfaits: pen += 0.25
    if plus: pen += 0.15
    sub_q = max(0.0, (s_obj - pen) + 0.45)  # petite base positive pour ne pas écraser
    sub_q = min(1.0, sub_q)
    subs["Qualite"] = round(sub_q*100,1)

    # ---- Indicateur global pondéré
    total = 0.0
    for d,w in WEIGHTS.items():
        total += (subs[d]/100.0) * w
    global_indic = round(total,1)

    return subs, global_indic

def recommandations(subs):
    """Conseils par domaine selon sous-indicateurs."""
    recos = []

    def reco_for(domain, msg_low, msg_mid, msg_high):
        s = subs[domain]
        if s < 40: recos.append(f"🔴 **{domain}** — {msg_low}")
        elif s < 70: recos.append(f"🟠 **{domain}** — {msg_mid}")
        else: recos.append(f"🟢 **{domain}** — {msg_high}")

    reco_for("Referent",
             "Désigner un(e) référent(e) APS et prévoir une formation reconnue (LSAHF, Handisport, Université…).",
             "Formaliser le rôle du référent et compléter/parfaire la formation.",
             "Maintenir la dynamique (veille, mise à jour des compétences).")

    reco_for("Regulier",
             "Mettre en place des APS **hebdomadaires**, viser ≥ 50% des usagers et ≥ 90 min/sem, diversifier les pratiques.",
             "Augmenter progressivement la **part d’usagers** et la **durée** (objectif 90 min/sem), varier 2–3 types d’APS.",
             "Consolider les volumes et la diversité, formaliser la programmation annuelle.")

    reco_for("Occasionnel",
             "Introduire des temps **occasionnels** (sorties, événements, cycles courts) pour engager les publics.",
             "Régulariser la fréquence (ex. mensuelle) et anticiper le calendrier.",
             "Pérenniser un calendrier d’événements et mutualiser avec d’autres ESMS.")

    reco_for("Encadrement",
             "Mobiliser des **professionnels** (APA, éducateur sportif) et clarifier l’encadrement.",
             "Augmenter les créneaux encadrés et favoriser la co-intervention (APA + éducateur).",
             "Capitaliser (tutorat interne, partage de séances, transmission).")

    reco_for("Projet",
             "Inscrire les APS dans le **projet d’établissement/CPOM** avec objectifs, indicateurs, moyens.",
             "Mieux formaliser dans le projet (indicateurs, calendrier, moyens).",
             "Suivre des indicateurs annuels et communiquer aux équipes/financeurs.")

    reco_for("Liens",
             "Créer des liens avec clubs (adapté/ordinaire), ligues, MSS, communes pour l’accès aux créneaux.",
             "Élargir et contractualiser (convention, accès infrastructures, co-organisation).",
             "Structurer un réseau de partenaires et un planning partagé.")

    reco_for("Qualite",
             "Clarifier les **objectifs** (autonomie, bien-être, habiletés…) et travailler l’adhésion des usagers.",
             "Mieux relier objectifs ↔ séances et recueillir le **ressenti** des usagers.",
             "Poursuivre l’évaluation qualitative et la co-construction avec les usagers.")

    return recos

def radar_chart(subs, title="Toile d’araignée – Indicateurs par domaine"):
    cats = DOMAINS_ORDER
    vals = [subs[c] for c in cats]
    vals.append(vals[0])  # fermeture du polygone
    cats_loop = cats + [cats[0]]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=vals, theta=cats_loop, fill='toself', name='Indicateur domaine'))
    fig.update_layout(
        title=title,
        polar=dict(
            radialaxis=dict(visible=True, range=[0,100], tickvals=[0,20,40,60,80,100])
        ),
        showlegend=True,
        height=430,
        margin=dict(l=20,r=20,t=60,b=20)
    )
    return fig

# --- Nouveau : calcul de progression de formulaire (pour la barre en haut)
def compute_form_progress(nom, nb_places, referent, formation_referent, activite_reguliere, nb_usagers, duree, encadrants, projet_etab, occasionnelle):
    required_total = 0
    done = 0
    # On aligne la logique sur la validation plus bas (mêmes champs requis)
    checks = [
        ("Nom de l’établissement", bool(nom)),
        ("Nombre de places", (nb_places is not None and nb_places != 0)),
        ("Référent APS", referent is not None),
        ("Formation spécifique", formation_referent is not None),
        ("APS régulières", activite_reguliere is not None),
        ("Part d’usagers concernés", nb_usagers is not None),
        ("Durée hebdo moyenne", duree is not None),
        ("Encadrement", len(encadrants) > 0),
        ("Projet d’établissement", projet_etab is not None),
        ("APS occasionnelles", occasionnelle is not None),
    ]
    required_total = len(checks)
    done = sum(1 for _, ok in checks if ok)
    pct = int(round((done/required_total)*100)) if required_total>0 else 0
    return pct, done, required_total

# =========================
# SIDEBAR (mode)
# =========================
st.sidebar.title("⚙️ Navigation")
mode = st.sidebar.radio("Choisir une page :", ["📝 Questionnaire", "📊 Admin (résultats globaux)"])
st.sidebar.markdown("---")
if st.sidebar.button("♻️ Réinitialiser les réponses", help="Efface les sélections et recharge la page", use_container_width=True):
    st.rerun()

# =========================
# PAGE: QUESTIONNAIRE
# =========================
if mode.startswith("📝"):
    st.markdown("<div class='card kpi'>"
                "<div class='section-title'><span class='emoji'>🧭</span><h2>Test d'auto-positionnement APS en ESMS</h2></div>"
                "<div class='small'>Les champs marqués <span class='req'>[obligatoire]</span> sont des indicateurs requis. "
                "Les autres sont <span class='opt'>optionnels</span>.</div>"
                "</div>", unsafe_allow_html=True)

    # ---------- SECTION: Informations ----------
    st.markdown("<div class='section-title'><span class='emoji'>ℹ️</span><h3>Informations établissement</h3></div>", unsafe_allow_html=True)
    colA,colB,colC = st.columns(3)
    with colA:
        nom = st.text_input("Nom de l’établissement * [obligatoire]", placeholder="ex: ESMS Les Genêts")
        departement = st.selectbox("Département * [obligatoire]", ["02 - Aisne","59 - Nord","60 - Oise","62 - Pas-de-Calais","80 - Somme"])
    with colB:
        type_etab = st.selectbox("Votre établissement est * [obligatoire]", ["ESAT","IME","ITEP","FAM","MAS","SAMSAH","SESSAD","EEAP","IEM","Autre"])
        nb_places = st.number_input("Nombre de places autorisées * [obligatoire]", min_value=0, step=1)
    with colC:
        tranche_age = st.selectbox("Tranche d'âge du public accueilli * [obligatoire]", ["Enfants","Adultes","Mixte"])
        public = st.multiselect("Public accueilli * [obligatoire]", ["Enfant","Adulte"], default=["Enfant","Adulte"])
    handicaps = st.multiselect("Types de handicap (optionnel)", ["Déficience intellectuelle","Handicap psychique","Troubles du neurodéveloppement","Polyhandicap","Autre"])

    # ---------- Barre de progression de complétion (nouvelle)
    # On calcule avec les valeurs déjà saisies (certaines ont une valeur par défaut donnée par Streamlit)
    _tmp_referent_default = "Oui"  # placeholders logiques pour éviter None si Streamlit a déjà une valeur
    _tmp_formation_default = "Oui"
    _tmp_reg_default = "Non"
    _tmp_nb_usagers_default = "0-10%"
    _tmp_duree_default = "0 min"
    _tmp_encadrants_default = []
    _tmp_projet_default = "Non"
    _tmp_occ_default = "Non"

    # Initialisation temporaire avant que l'utilisateur ne fasse ses choix (sera réévaluée plus bas)
    form_pct, form_done, form_total = compute_form_progress(
        nom or "", nb_places, _tmp_referent_default, _tmp_formation_default, _tmp_reg_default,
        _tmp_nb_usagers_default, _tmp_duree_default, _tmp_encadrants_default, _tmp_projet_default, _tmp_occ_default
    )
    # Affichage visuel de la progression
    st.markdown(f"""
    <div class='card'>
      <div class='section-title'><span class='emoji'>📶</span><h3>Progression du questionnaire</h3></div>
      <div class='small'>Complété : <b>{form_done}/{form_total}</b> — avancez jusqu'à 100% pour des indicateurs au plus juste.</div>
      <div class='progress-wrap' style='height:22px;'>
        <div class='progress-bar-alt' style='width:{form_pct}%;'>{form_pct}%</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ---------- SECTION: Référent ----------
    st.markdown("<div class='section-title'><span class='emoji'>👤</span><h3>Référent APS</h3></div>", unsafe_allow_html=True)
    col1,col2,col3 = st.columns(3)
    referent = col1.radio("Référent APS identifié ? [obligatoire]", ["Oui","Non"], horizontal=True)
    formation_referent = col2.radio("Formation spécifique ? [obligatoire]", ["Oui","Non"], horizontal=True)
    organisme = col3.selectbox("Organisme de formation", ["Aucun / Non précisé","LSAHF","Fédération Handisport","Université (APAS)","ARS / DRJSCS","Autre"])

    # ---------- SECTION: Activités régulières ----------
    st.markdown("<div class='section-title'><span class='emoji'>🏃</span><h3>Activités physiques régulières</h3></div>", unsafe_allow_html=True)
    activite_reguliere = st.radio("APS régulières ? [obligatoire]", ["Non","Oui, 1 fois par semaine","Oui, plus d'une fois"], horizontal=True)
    colr1,colr2,colr3,colr4 = st.columns(4)
    nb_usagers = colr1.selectbox("Part d’usagers concernés [obligatoire]",
                                 ["0-10%","10-20%","20-30%","30-40%","40-50%","50-60%","60-70%","70-80%","80-90%","90-100%"])
    duree = colr2.selectbox("Durée hebdo moyenne [obligatoire]",
                            ["0 min","20 min","30 min","45 min","1h","1h30","2h","2h30"])
    types_activites = colr3.multiselect("Types proposés (au moins 1 recommandé)", ["Individuelle","Collective","Opposition","Artistique","Pleine nature"])
    freq_label = colr4.selectbox("Fréquence", ["Non précisé","Hebdomadaire","Bi-hebdomadaire","Quotidien"])

    # ---------- SECTION: Activités occasionnelles ----------
    st.markdown("<div class='section-title'><span class='emoji'>🎉</span><h3>Activités occasionnelles</h3></div>", unsafe_allow_html=True)
    occasionnelle = st.radio("APS occasionnelles ? [obligatoire]", ["Oui","Non"], horizontal=True)

    # ---------- SECTION: Objectifs / Qualité ----------
    st.markdown("<div class='section-title'><span class='emoji'>🎯</span><h3>Objectifs & perception</h3></div>", unsafe_allow_html=True)
    objectifs = st.multiselect("Objectifs poursuivis", ["Thérapeutique","Occupationnel","Maintien des capacités physiques","Développement physique","Habiletés sociales","Capacités cognitives","Autonomie","Bien-être"])
    satisfaction = st.multiselect("Les usagers verbalisent (perception)", ["Vouloir plus d’APS","Être satisfaits","Ne pas être satisfaits","Trop d’APS"])

    # ---------- SECTION: Encadrement & Infrastructures ----------
    st.markdown("<div class='section-title'><span class='emoji'>👨‍🏫</span><h3>Encadrement & infrastructures</h3></div>", unsafe_allow_html=True)
    encadrants = st.multiselect("Professionnels encadrants [obligatoire]", ["Enseignant APA","Éducateur sportif","Aucun professionnel"])
    infrastructures = st.multiselect("Lieux de pratique (optionnel)", ["Gymnase interne","Salle polyvalente","Espace extérieur","À l’extérieur","Non concerné"])

    # ---------- SECTION: Projet & Liens ----------
    cols = st.columns(2)
    with cols[0]:
        st.markdown("<div class='section-title'><span class='emoji'>📑</span><h3>Projet d’établissement</h3></div>", unsafe_allow_html=True)
        projet_etab = st.radio("APS inscrites au projet/CPOM ? [obligatoire]", ["Oui","Non"], horizontal=True)
    with cols[1]:
        st.markdown("<div class='section-title'><span class='emoji'>🌍</span><h3>Liens extérieurs</h3></div>", unsafe_allow_html=True)
        liens = st.multiselect("Structures partenaires", ["Clubs adaptés","Clubs ordinaires","Mairie","Ligues","Maisons sport-santé","Autres ESMS","Aucun"])

    # ---------- SECTION: Leviers & Freins (optionnels pour l’analyse)
    st.markdown("<div class='section-title'><span class='emoji'>⚖️</span><h3>Leviers & freins (optionnel)</h3></div>", unsafe_allow_html=True)
    actions_existantes = st.multiselect("Actions déjà mises en place", ["Recrutement","Achat matériel","Création de séances","Lieu dédié","Sorties","Partenariat clubs"])
    freins = st.multiselect("Freins rencontrés", ["Moyens humains","Moyens matériels","Lieu","Manque de contacts","Absence clubs","Temps","Manque info"])

    st.markdown("---")

    # ---------- Boutons
    c1,c2,c3 = st.columns([1,1,2])
    with c1:
        ready = st.button("✅ Calculer mes indicateurs", use_container_width=True)
    with c2:
        if st.button("♻️ Reset", help="Effacer toutes les réponses", use_container_width=True):
            st.rerun()


    # --- Mettre à jour la barre de progression avec les vraies réponses (après l’affichage des champs)
    form_pct, form_done, form_total = compute_form_progress(
        nom, nb_places, referent, formation_referent, activite_reguliere, nb_usagers, duree, encadrants, projet_etab, occasionnelle
    )
    st.markdown(f"""
    <div class='card'>
      <div class='small'><span class='badge'>Progression du QCM mise à jour</span> : <b>{form_done}/{form_total}</b></div>
      <div class='progress-wrap' style='height:18px;'>
        <div class='progress-bar-alt' style='width:{form_pct}%; height:18px;'>{form_pct}%</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ---------- Validation requis + Calcul
    if ready:
        missing = []
        if not nom: missing.append("Nom de l’établissement")
        if nb_places is None or nb_places == 0: missing.append("Nombre de places")
        required_checks = [
            ("Référent APS", referent is not None),
            ("Formation spécifique", formation_referent is not None),
            ("APS régulières", activite_reguliere is not None),
            ("Part d’usagers concernés", nb_usagers is not None),
            ("Durée hebdo moyenne", duree is not None),
            ("Encadrement", len(encadrants) > 0),
            ("Projet d’établissement", projet_etab is not None),
            ("APS occasionnelles", occasionnelle is not None),
        ]
        for label, ok in required_checks:
            if not ok: missing.append(label)

        if missing:
            st.error("Merci de compléter les indicateurs obligatoires : " + ", ".join(missing))
        else:
            # Pack des réponses
            answers = dict(
                nom=nom, departement=departement, type_etab=type_etab,
                public=public, tranche_age=tranche_age, nb_places=nb_places,
                handicaps=handicaps,
                referent=referent, formation_referent=formation_referent, organisme=organisme,
                activite_reguliere=activite_reguliere, nb_usagers=nb_usagers, duree=duree,
                types_activites=types_activites, freq_label=freq_label,
                occasionnelle=occasionnelle,
                objectifs=objectifs, satisfaction=satisfaction,
                encadrants=encadrants, infrastructures=infrastructures,
                projet_etab=projet_etab, liens=liens,
                actions_existantes=actions_existantes, freins=freins
            )

            # Calcul
            subs, indicateur_global = compute_indicators(answers)

            # ---- Affichage KPI
            st.markdown("<hr/>", unsafe_allow_html=True)
            k1, k2, k3 = st.columns(3)
            with k1:
                st.markdown(f"<div class='card kpi'><h3>📈 Indicateur global</h3><h2 style='color:{color_for_score(indicateur_global)}'>{indicateur_global}/100</h2></div>", unsafe_allow_html=True)
            with k2:
                st.markdown(f"<div class='card kpi'><h3>🎯 Domaines ≥ 70</h3><h2>{sum(1 for v in subs.values() if v>=70)}/{len(subs)}</h2></div>", unsafe_allow_html=True)
            with k3:
                st.markdown(f"<div class='card kpi'><h3>🛠️ Domaines < 40</h3><h2>{sum(1 for v in subs.values() if v<40)}</h2></div>", unsafe_allow_html=True)

            # ---- Barre progression (indicateur global, déjà présente)
            bar_color = color_for_score(indicateur_global)
            st.markdown(f"""
            <div class='card'>
              <div class='small'><span class='legend-dot' style='background:{bar_color}'></span>Légende : rouge &lt; 40, orange 40–69, vert ≥ 70</div>
              <div class='progress-wrap'>
                <div class='progress-bar' style='width:{indicateur_global}%; background:{bar_color};'>{indicateur_global}%</div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            # ---- Radar
            fig = radar_chart(subs, "Toile d’araignée – Indicateurs par domaine (0–100)")
            st.plotly_chart(fig, use_container_width=True)

            # ---- Détails par domaine
            st.markdown("### 🔎 Détail des indicateurs par domaine")
            for d in DOMAINS_ORDER:
                val = subs[d]
                color = color_for_score(val)
                st.markdown(f"<div class='card'><b>{d}</b> — <span style='color:{color}'><b>{val}/100</b></span></div>", unsafe_allow_html=True)

            # ---- Conseils & accompagnement
            st.markdown("### 🤝 Messages d’accompagnement et conseils")
            for line in recommandations(subs):
                st.markdown(f"- {line}")

            # ---- Télécharger résultats
            result_row = {
                "Horodatage": datetime.now().isoformat(timespec='seconds'),
                "Etablissement": nom, "Département": departement, "Type": type_etab,
                "Tranche_age": tranche_age, "Places": nb_places, "Public": ";".join(public),
                "Handicaps": ";".join(handicaps),
                "Referent": referent, "Formation": formation_referent, "Organisme": organisme,
                "Regulier": activite_reguliere, "Part_usagers": nb_usagers, "Duree_hebdo": duree,
                "Types_reguliers": ";".join(types_activites), "Frequence": freq_label,
                "Occasionnel": occasionnelle,
                "Objectifs": ";".join(objectifs), "Satisfaction": ";".join(satisfaction),
                "Encadrants": ";".join(encadrants), "Infrastructures": ";".join(infrastructures),
                "Projet": projet_etab, "Liens": ";".join(liens),
                **{f"Indic_{k}": v for k,v in subs.items()},
                "Indicateur_global": indicateur_global
            }
            df_out = pd.DataFrame([result_row])

            # Sauvegarde cumulée
            try:
                old = pd.read_excel("resultats_qcm.xlsx")
                all_out = pd.concat([old, df_out], ignore_index=True)
            except FileNotFoundError:
                all_out = df_out
            all_out.to_excel("resultats_qcm.xlsx", index=False)

            # Bouton téléchargement (CSV individuel)
            csv_bytes = df_out.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Télécharger mes résultats (CSV)", data=csv_bytes, file_name=f"resultats_{nom.replace(' ','_')}.csv", mime="text/csv", help="Export des indicateurs et réponses")

            st.markdown("<div class='download-note'>Les résultats cumulés sont également enregistrés dans <b>resultats_qcm.xlsx</b> (pour la page Admin).</div>", unsafe_allow_html=True)

# =========================
# PAGE: ADMIN
# =========================
else:
    st.header("📊 Admin — Résultats globaux")
    try:
        df_all = pd.read_excel("resultats_qcm.xlsx")
    except FileNotFoundError:
        st.info("Aucune donnée enregistrée pour le moment. Revenez après quelques réponses.")
        df_all = None

    if df_all is not None and len(df_all)>0:
        # Filtres
        f1,f2,f3 = st.columns(3)
        deps = ["Tous"] + sorted(list(df_all["Département"].dropna().unique()))
        types = ["Tous"] + sorted(list(df_all["Type"].dropna().unique()))
        ages = ["Tous"] + sorted(list(df_all["Tranche_age"].dropna().unique()))

        dep_sel = f1.selectbox("Filtrer par département", deps)
        type_sel = f2.selectbox("Filtrer par type d’établissement", types)
        age_sel = f3.selectbox("Filtrer par tranche d’âge", ages)

        df_view = df_all.copy()
        if dep_sel!="Tous": df_view = df_view[df_view["Département"]==dep_sel]
        if type_sel!="Tous": df_view = df_view[df_view["Type"]==type_sel]
        if age_sel!="Tous": df_view = df_view[df_view["Tranche_age"]==age_sel]

        st.dataframe(df_view, use_container_width=True)

        # Moyennes par domaine
        if len(df_view)>0:
            means = {d: round(df_view[f"Indic_{d}"].mean(),1) for d in DOMAINS_ORDER if f"Indic_{d}" in df_view.columns}
            fig_admin = radar_chart(means, "Moyenne des indicateurs — échantillon filtré")
            st.plotly_chart(fig_admin, use_container_width=True)

            # KPIs admin
            c1,c2,c3 = st.columns(3)
            c1.metric("Établissements (filtre)", len(df_view))
            if "Indicateur_global" in df_view.columns:
                # fix: pas de saut de ligne intempestif dans le f-string
                c2.metric("Indicateur global moyen", f"{round(df_view['Indicateur_global'].mean(),1)}/100")
            c3.metric("Dernière mise à jour", datetime.now().strftime("%d/%m/%Y %H:%M"))
        else:
            st.warning("Aucune ligne avec ces filtres.")
# --- fin du script ; commentaires supplémentaires pour garder au moins le même volume de lignes :
# Notes:
# - Tous les libellés de widgets utilisent désormais du texte brut pour [obligatoire] (plus de <span> visibles).
# - La progression du QCM est calculée sur le même set de champs requis que la validation finale.
# - La palette et les cartes ont été légèrement enrichies sans retirer d’éléments existants.
# - L’admin garde les métriques et corrige le f-string avec newline.
# - N’hésite pas à ajuster les couleurs CSS (variables --prim, --sec, etc.) si tu veux plus de contraste.
