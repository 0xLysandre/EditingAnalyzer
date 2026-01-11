import streamlit as st
import pandas as pd
import time
import os
from youtube_prospector import run_prospector

# Configuration de la page
st.set_page_config(
    page_title="YouTube Prospector Pro",
    page_icon="💎",
    layout="wide"
)

# Titre
st.title("💎 YouTube Prospector Pro")
st.markdown("Trouvez des clients qualifiés pour votre offre de montage vidéo.")

# Sidebar - Configuration
with st.sidebar:
    st.header("🔑 Authentification")
    
    # Gestion sécurisée de la clé API
    try:
        env_key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        env_key = None
        
    if not env_key:
        env_key = os.environ.get("GROQ_API_KEY")
    
    # Si clé trouvée dans l'environnement/secrets, on l'utilise et on cache l'input
    if env_key:
        final_api_key = env_key
        st.success("✅ Clé API chargée (Env/Secrets)")
    else:
        # Sinon, saisie manuelle
        input_key = st.text_input("Clé API Groq", type="password", help="La clé n'est pas sauvegardée.")
        if input_key:
            final_api_key = input_key
            st.warning("⚠️ Clé temporaire active")
        else:
            final_api_key = None
    
    st.divider()

    st.header("🎯 Cible")
    niche = st.text_input("Niche", value="crypto")
    language = st.selectbox("Langue", options=["fr", "en"], index=0)
    
    st.divider()
    
    st.header("⚙️ Paramètres")
    max_analyze = st.number_input("Max vidéos à analyser", min_value=1, max_value=100, value=10)
    
    col1, col2 = st.columns(2)
    with col1:
        subs_min = st.number_input("Abonnés Min", value=5000, step=1000)
    with col2:
        subs_max = st.number_input("Abonnés Max", value=500000, step=10000)
        
    min_duration = st.number_input("Durée Min (minutes)", value=8, help="Pour le scoring (non bloquant sur le moteur actuel)")
    
    export_csv = st.checkbox("Générer CSV", value=True)
    
    st.divider()
    
    launch_btn = st.button("🚀 Lancer l'analyse", type="primary", disabled=not final_api_key)
    if not final_api_key:
        st.caption("🔒 Veuillez entrer une clé API pour commencer.")

# Initialisation Session State
if "results" not in st.session_state:
    st.session_state.results = None

# Logique principale
if launch_btn:
    if not niche:
        st.error("Veuillez spécifier une niche.")
    else:
        # Interface de logs
        status_container = st.status("Analyse en cours...", expanded=True)
        progress_bar = status_container.progress(0)
        log_text = status_container.empty()
        
        logs = []
        
        def streamlit_logger(msg):
            # Callback pour afficher les logs en temps réel
            logs.append(msg)
            # On affiche juste la dernière ligne ou tout le bloc
            log_text.code("\n".join(logs[-10:])) # Garde les 10 dernières lignes pour propreté
            
            # Mise à jour barre de progression (estimation basique)
            # On essaie de détecter le % basé sur "Analyse:"
            if "Analyse:" in msg or "Recherche" in msg:
                # Logique simplifiée : on incremente doucement
                pass

        try:
            # Exécution du moteur
            # Note: min_duration n'est pas encore accepté par run_prospector, on le garde pour future implémentation
            results = run_prospector(
                niche=niche,
                language=language,
                max_analyze=max_analyze,
                subs_min=subs_min,
                subs_max=subs_max,
                api_key=final_api_key,
                logger=streamlit_logger
            )
            
            st.session_state.results = results
            progress_bar.progress(100)
            status_container.update(label="Analyse terminée !", state="complete", expanded=False)
            
        except Exception as e:
            status_container.update(label="Erreur survenue", state="error")
            st.error(f"Erreur critique : {str(e)}")

# Affichage des Résultats
if st.session_state.results:
    res = st.session_state.results
    summary = res["summary"]
    rows = res["rows"]
    
    # 1. Métriques
    col1, col2, col3 = st.columns(3)
    col1.metric("Vidéos Trouvées", summary["total_found"])
    col2.metric("Analysées", summary["analyzed"])
    col3.metric("Qualifiés", summary["qualified"])
    
    st.divider()
    
    # 2. Tableau des Leads Qualifiés
    st.subheader("🏆 Leads Qualifiés")
    
    qualified_rows = [r for r in rows if r["analysis"].get("needs_editor")]
    
    if qualified_rows:
        for q in qualified_rows:
            a = q["analysis"]
            
            # Titre de l'expander : Nom Chaîne + Score
            with st.expander(f"⭐ {q['channel']} (Score: {a['lead_score']}/100)"):
                
                # Colonnes Détails
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Titre :** [{q['video_title']}]({q['url']})")
                    st.write(f"**Abonnés :** {q['subscriber_count']}")
                with c2:
                    st.write(f"**Preuves :** {', '.join(a.get('evidence', []))}")
                    st.caption(f"upload: {q['upload_date']}")
                
                st.divider()
                
                # Messages copiables
                m1, m2 = st.columns(2)
                with m1:
                    st.text_area("Message Option 1", value=a.get("message_option_1"), height=100)
                with m2:
                    st.text_area("Message Option 2", value=a.get("message_option_2"), height=100)
    else:
        st.info("Aucun lead qualifié trouvé avec ces critères.")

    # 3. Export CSV
    if res.get("csv_content"):
        st.divider()
        st.download_button(
            label="💾 Télécharger prospects.csv",
            data=res["csv_content"],
            file_name=f"leads_{niche}_{int(time.time())}.csv",
            mime="text/csv"
        )
        
    # 4. Rejets (Expander)
    with st.expander("🗑️ Voir les vidéos rejetées"):
        if res["rejections"]:
            st.table(pd.DataFrame(res["rejections"]))
        else:
            st.write("Aucun rejet explicite enregistré.")
