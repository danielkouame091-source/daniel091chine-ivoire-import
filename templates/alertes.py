"""
alertes.py — BaobabVault ERP
Intégration Africa's Talking pour l'envoi réel de SMS d'alerte
(échecs de connexion, kill-switch, comptes gelés).

Installation :
    pip install africastalking

Secrets requis (st.secrets) :
    AT_USERNAME   = "sandbox"           # ou ton nom de compte en production
    AT_API_KEY    = "..."               # clé API depuis africastalking.com
    AT_SENDER_ID  = ""                  # optionnel : ID expéditeur validé
    FOUNDER_PHONE = "+225XXXXXXXXX"     # numéro à alerter en cas de kill-switch

Mode sandbox : crée un compte gratuit sur https://account.africastalking.com,
utilise "sandbox" comme AT_USERNAME et la clé API sandbox — aucun SMS réel
n'est facturé, mais le flux complet est testable (numéros de test fournis
par Africa's Talking).
"""

import streamlit as st

try:
    import africastalking
except ImportError:
    africastalking = None

_sms_service = None  # initialisé une seule fois (paresseux)


def _get_sms_service():
    global _sms_service
    if _sms_service is not None:
        return _sms_service

    if africastalking is None:
        return None

    username = st.secrets.get("AT_USERNAME", "") if hasattr(st, "secrets") else ""
    api_key = st.secrets.get("AT_API_KEY", "") if hasattr(st, "secrets") else ""
    if not username or not api_key:
        return None

    africastalking.initialize(username, api_key)
    _sms_service = africastalking.SMS
    return _sms_service


def api_configuree() -> bool:
    return _get_sms_service() is not None


def envoyer_sms(numeros: list[str], message: str) -> dict:
    """
    Envoie un SMS réel via Africa's Talking à un ou plusieurs numéros
    (format international, ex: "+2250700000000").
    Retourne {"succes": bool, "details": ...} — ne lève jamais d'exception
    non gérée pour ne pas casser le flux applicatif (login, kill-switch)
    si l'API est indisponible ou mal configurée.
    """
    service = _get_sms_service()
    if service is None:
        return {"succes": False, "details": "Africa's Talking non configuré (package absent ou secrets manquants) — alerte journalisée seulement."}

    sender_id = st.secrets.get("AT_SENDER_ID", "") if hasattr(st, "secrets") else ""
    try:
        if sender_id:
            reponse = service.send(message, numeros, sender_id)
        else:
            reponse = service.send(message, numeros)
        return {"succes": True, "details": reponse}
    except Exception as e:
        return {"succes": False, "details": f"Erreur API Africa's Talking : {e}"}


def envoyer_whatsapp(numero: str, message: str) -> dict:
    """
    Africa's Talking propose aussi une API WhatsApp Business, mais elle
    exige un numéro WhatsApp Business validé ET des modèles de message
    pré-approuvés par Meta pour tout message hors fenêtre de 24h de
    conversation active. Structure d'appel (à activer une fois le
    numéro WhatsApp Business et le modèle approuvés côté Africa's Talking) :

        africastalking.initialize(username, api_key)
        whatsapp = africastalking.WhatsApp
        whatsapp.send_message({
            "phoneNumber": numero,
            "wabaNumber": st.secrets["AT_WHATSAPP_NUMBER"],
            "message": {"templateName": "alerte_urgence", "language": "fr", "params": [message]},
        })

    Non activé par défaut ici (nécessite une configuration préalable côté
    Africa's Talking) — on retombe sur le SMS classique en attendant.
    """
    return envoyer_sms([numero], message)


def alerte_urgence_founder(message: str) -> dict:
    """Raccourci : alerte le numéro du fondateur (FOUNDER_PHONE dans les secrets)."""
    numero = st.secrets.get("FOUNDER_PHONE", "") if hasattr(st, "secrets") else ""
    if not numero:
        return {"succes": False, "details": "FOUNDER_PHONE non configuré dans les secrets."}
    return envoyer_sms([numero], message)
