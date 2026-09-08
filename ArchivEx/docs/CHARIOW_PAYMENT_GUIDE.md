# Guide d'Intégration & Configuration Chariow pour ArchivEx

Ce document décrit la configuration, le fonctionnement et la maintenance du système de paiement **Chariow** intégré à ArchivEx.

---

## 1. Vue d'Ensemble de l'Intégration

ArchivEx utilise l'API officielle **Chariow Checkout** et le système de webhooks **Pulses** pour encaisser les paiements des Pass Semestre (4 500 FCFA) et activer automatiquement l'accès aux examens, résumés et guides.

### Flux de Paiement Sécurisé

```
Étudiant connecté sur ArchivEx
       ↓
Sélectionne « Pass Semestre (4 500 FCFA) » et saisit son numéro de téléphone
       ↓
Django enregistre un Payment en statut 'PENDING'
       ↓
Django appelle côté serveur POST https://api.chariow.com/v1/checkout
(avec product_id, email, phone, custom_metadata, redirect_url)
       ↓
Chariow renvoie payment.checkout_url
       ↓
Redirection de l'étudiant vers la page de paiement sécurisée Chariow
       ↓
L'étudiant règle via Mobile Money (MTN MoMo, Moov Money, etc.)
       ↓
Chariow envoie un Pulse (Webhook) POST /pass/webhook/chariow/
       ↓
Django vérifie la signature HMAC-SHA256 (header x-chariow-signature)
       ↓
Si event == 'successful.sale' :
  - Paiement marqué APPROVED
  - Activation de SemesterAccess et UserSubscription (180 jours)
  - Enregistrement de chariow_sale_id
       ↓
Redirection de l'étudiant vers la page de confirmation ArchivEx
```

---

## 2. Variables d'Environnement (.env)

Dans votre fichier `.env` sur le serveur, configurez les variables suivantes :

```ini
# === TARIF PASS SEMESTRE ===
PASS_SEMESTRE_PRIX_DEFAUT=4500


# === PASSERELLE DE PAIEMENT CHARIOW ===
# Clé API secrète générée depuis votre compte Chariow (Paramètres -> Clés API)
CHARIOW_API_KEY=sk_live_votre_cle_api_secrete

# Identifiant public du produit Pass Semestre créé sur Chariow (ex: prd_xxx ou slug)
CHARIOW_PRODUCT_ID=prd_pass_semestre_archivex

# Secret du Webhook Pulse généré lors de la création du Pulse dans Chariow
CHARIOW_PULSE_SECRET=votre_secret_pulse_chariow

# URL de base de l'API Chariow (par défaut)
CHARIOW_BASE_URL=https://api.chariow.com/v1

# Devise (Franc CFA UEMOA)
CHARIOW_CURRENCY=XOF
```

> [!CAUTION]
> **Ne committez jamais** votre fichier `.env` ou vos clés API dans Git. La clé API et le secret Pulse doivent impérativement rester strictement côté serveur.

---

## 3. Configuration dans le Tableau de Bord Chariow

### Étape 1 : Création du Produit Pass Semestre
1. Connectez-vous à votre tableau de bord [Chariow](https://dashboard.chariow.com).
2. Rendez-vous dans la section **Produits** (Products) → **Créer un produit**.
3. Renseignez :
   - **Nom** : `Pass Semestre ArchivEx`
   - **Type de produit** : Produit numérique / Accès (compatible avec l'API Checkout)
   - **Prix** : `4 500 FCFA` (Devise `XOF`)
   - **Statut** : **Publié** (Published)
4. Copiez l'**ID du produit** (ex: `prd_abc123xyz` ou le slug) et collez-le dans `CHARIOW_PRODUCT_ID` dans votre `.env`.

### Étape 2 : Création de la Clé API
1. Dans le tableau de bord Chariow, accédez à **Paramètres** → **Développeurs / Clés API**.
2. Créez une nouvelle clé API (ex: `ArchivEx Production`).
3. Copiez la clé secrète générée (`sk_live_...` ou `sk_test_...`) et collez-la dans `CHARIOW_API_KEY` dans votre `.env`.

### Étape 3 : Configuration du Webhook Pulse
1. Accédez à **Automation** → **Pulses** dans votre tableau de bord Chariow.
2. Cliquez sur **Ajouter un Pulse** (Add Pulse).
3. Renseignez l'URL de votre webhook HTTPS :
   ```
   https://votre-domaine.com/pass/webhook/chariow/
   ```
4. Sélectionnez les événements à écouter :
   - `successful.sale` (Vente réussie / Paiement validé)
   - `failed.sale` (Paiement échoué)
   - `abandoned.sale` (Vente abandonnée)
   - `refunded.sale` (Remboursement)
5. Filtre de produit : Sélectionnez le produit `Pass Semestre ArchivEx` ou laissez pour tous les produits.
6. Enregistrez et copiez le **Secret du Pulse** fourni par Chariow.
7. Collez ce secret dans `CHARIOW_PULSE_SECRET` dans votre `.env`.

---

## 4. Sécurité & Bonnes Pratiques

1. **Vérification HMAC-SHA256** : Le webhook d'ArchivEx rejette immédiatement toute requête dont la signature transmise dans le header `x-chariow-signature` ne correspond pas au hachage du corps brut (`raw body`) avec votre `CHARIOW_PULSE_SECRET`.
2. **Idempotence** : Si Chariow renvoie un même webhook à plusieurs reprises, ArchivEx détecte que le paiement est déjà `APPROVED` et acquitte la requête (HTTP 200) sans jamais créer de doublon d'abonnement ni recalculer la période de validité.
3. **Sécurité des logs** : Les clés d'API et secrets ne sont jamais journalisés en clair dans les logs serveur (`archivex_error.log`).
4. **HTTPS Obligatoire** : Les endpoints de webhooks doivent toujours utiliser HTTPS en production.

---

## 5. Tests et Vérification en Local / Staging

### Tester les endpoints avec Django Test Suite
Exécutez la suite de tests automatisés :
```bash
python manage.py test payments subscriptions
```

### Tester les Webhooks en Local avec un Tunnel (ex: ngrok)
1. Démarrez un tunnel sécurisé :
   ```bash
   ngrok http 8000
   ```
2. Dans le tableau de bord Chariow, définissez l'URL du Pulse sur :
   ```
   https://xxxx.ngrok-free.app/pass/webhook/chariow/
   ```
3. Effectuez un paiement test via l'interface ArchivEx.
4. Vérifiez dans la console Django la réception du Pulse et l'activation du Pass.
