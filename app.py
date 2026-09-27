import hashlib
import streamlit as st


# Fonction de hachage sécurisé des mots de passe
def make_hashes(password):
  return hashlib.sha256(str.encode(password)).hexdigest()


def check_hashes(password, hashed_text):
  if make_hashes(password) == hashed_text:
    return True
  return False


# Base de données simulée des utilisateurs et de leurs rôles
USERS_DB = {
    "admin": {
        "password": make_hashes("admin123"),
        "role": "Administrateur",
        "nom": "Kouassi Admin",
    },
    "verificateur": {
        "password": make_hashes("veri123"),
        "role": "Vérificateur",
        "nom": "Inspecteur Douane",
    },
    "caisse": {
        "password": make_hashes("caisse123"),
        "role": "Agent de Caisse",
        "nom": "Caissier Principal",
    },
    "transit": {
        "password": make_hashes("transit123"),
        "role": "Commissionnaire agréé",
        "nom": "Mandataire Transit",
    },
}


def main():
  st.set_page_config(
      page_title="SNDGIR v5.0 - Connexion Sécurisée", layout="wide"
  )

  # Initialisation des variables de session
  if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.session_state["nom"] = ""

  # Interface de connexion si l'utilisateur n'est pas connecté
  if not st.session_state["logged_in"]:
    st.title("SNDGIR v5.0 - Portail de Connexion")
    st.markdown("Veuillez vous authentifier pour accéder à votre espace.")

    with st.form("login_form"):
      st.subheader("Authentification Sécurisée")
      username = st.text_input("Nom d'utilisateur")
      password = st.text_input("Mot de passe", type="password")
      submit_button = st.form_submit_button("Se connecter")

      if submit_button:
        if (
            username in USERS_DB
            and check_hashes(password, USERS_DB[username]["password"])
        ):
          st.session_state["logged_in"] = True
          st.session_state["username"] = username
          st.session_state["role"] = USERS_DB[username]["role"]
          st.session_state["nom"] = USERS_DB[username]["nom"]
          st.success(f"Connexion réussie ! Bienvenue {st.session_state['nom']}")
          st.rerun()
        else:
          st.error(
              "Nom d'utilisateur ou mot de passe incorrect. Veuillez réessayer."
          )

  else:
    # --- BARRE LATÉRALE : INFORMATIONS ET DÉCONNEXION ---
    st.sidebar.title("Navigation & Session")
    st.sidebar.write(f"**Utilisateur :** {st.session_state['nom']}")
    st.sidebar.write(f"**Rôle :** {st.session_state['role']}")

    if st.sidebar.button("Déconnexion"):
      st.session_state["logged_in"] = False
      st.session_state["username"] = ""
      st.session_state["role"] = ""
      st.session_state["nom"] = ""
      st.rerun()

    # --- ROUTAGE DES MODULES SELON LE RÔLE ---
    role = st.session_state["role"]

    if role == "Administrateur":
      render_admin_dashboard()
    elif role == "Vérificateur":
      render_verificateur_dashboard()
    elif role == "Agent de Caisse":
      render_caisse_dashboard()
    elif role == "Commissionnaire agréé":
      render_transit_dashboard()


# --- MODULES SPÉCIFIQUES PAR RÔLE ---


def render_admin_dashboard():
  st.title("Tableau de Bord - Administrateur")
  st.info("Accès complet aux paramètres du système, des utilisateurs et des logs.")


def render_verificateur_dashboard():
  st.title("Tableau de Bord - Vérificateur des Douanes")
  st.info(
      "Module Douane & SAD : Validation des déclarations et gestion des"
      " circuits de sélectivité."
  )


def render_caisse_dashboard():
  st.title("Tableau de Bord - Agent de Caisse")
  st.info(
      "Module Caisse & BAE : Enregistrement des quittances et édition du Bon à"
      " Enlever."
  )


def render_transit_dashboard():
  st.title("Tableau de Bord - Commissionnaire Agrée en Douane")
  st.info(
      "Module Transit & Logistique : Suivi des dossiers, manifestes et calcul des"
      " surestaries."
  )


if __name__ == "__main__":
  main()
