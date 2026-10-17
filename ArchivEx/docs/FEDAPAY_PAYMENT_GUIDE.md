# Guide d'Intégration & Configuration FedaPay pour ArchivEx

Ce document décrit la configuration, le fonctionnement et la maintenance de la passerelle de paiement **FedaPay** intégrée à ArchivEx pour le Pass Semestre (4 500 FCFA).

---

## 1. Vue d'Ensemble

ArchivEx utilise l'API officielle **FedaPay** (Checkout v1) et le système de Webhooks sécurisés pour encaisser les paiements par Mobile Money (MTN MoMo, Moov Money, Celtiis Cash) et activer automatiquement l'accès aux examens, résumés et guides.

### Flux de Paiement Sécurisé

```
Étudiant connecté sur ArchivEx
       ↓
Sélectionne le Pass Semestre (4 500 FCFA) et saisit son numéro de téléphone béninois (+229)
       ↓
Django crée un Payment en statut 'PENDING'
       ↓
Django appelle côté serveur l'API FedaPay (/v1/transactions + /token)
       ↓
Redirection sécurisée de l'étudiant vers le guichet FedaPay
       ↓
L'étudiant valide la transaction sur son téléphone (MTN / Moov / Celtiis)
       ↓
FedaPay émet un Webhook signé (header X-FEDAPAY-SIGNATURE) vers /pass/webhook/fedapay/
       ↓
Django valide la signature et active instantanément le Pass Semestre (180 jours)
       ↓
Redirection de l'étudiant vers /pass/retour/ avec déblocage immédiat
```

---

## 2. Variables d'Environnement (.env)

Dans votre fichier `.env` :

```ini
# === TARIF PASS SEMESTRE ===
PASS_SEMESTRE_PRIX_DEFAUT=4500

# === CONFIGURATION FEDAPAY (https://fedapay.com) ===
# Mode : sandbox (tests) ou live (production)
FEDAPAY_ENVIRONMENT=live
FEDAPAY_SECRET_KEY=sk_live_votre_cle_secrete
FEDAPAY_PUBLIC_KEY=pk_live_votre_cle_publique
FEDAPAY_WEBHOOK_SECRET=wh_live_votre_secret_webhook
FEDAPAY_CURRENCY=XOF
```

---

## 3. Webhook FedaPay

- **URL de Webhook** : `https://archivex.bj/pass/webhook/fedapay/`
- **Événements supportés** : `transaction.approved`, `transaction.canceled`, etc.
- **Sécurité** : Validation de la signature HMAC-SHA256 et fallback par interrogation directe de l'API FedaPay serveur-à-serveur.
