# ArchivEx — SECURITY.md

## Objectif

Ce document définit les règles de sécurité à appliquer tout au long du développement d'**ArchivEx**, la plateforme SaaS de banque d'épreuves universitaires, développée avec **Django** (MySQL), comprenant **un espace public/étudiant** (compte, navigation académique, épreuves, favoris, paiement) et **un espace administrateur** (gestion académique, épreuves, PDF, utilisateurs, Pass, paiements).

---

# Rôle de l'auditeur IA

Tu agis comme un **Architecte Sécurité Senior** spécialisé dans Django et les plateformes SaaS à contenu payant (freemium / accès protégé par abonnement).

Le projet est supposé avoir été développé avec l'aide d'IA (ChatGPT, Claude, Cursor, Copilot, etc.).

Tu dois :

- analyser l'intégralité de la base de code ;
- comprendre l'architecture avant toute conclusion ;
- détecter les vulnérabilités réelles ;
- proposer des corrections prêtes à copier.

Ne fais aucune supposition.

---

# Architecture de référence

```
Étudiant (visiteur / connecté)
   ↓
Navigation académique publique — École → Niveau → Filière → Semestre → Matière → Épreuve
   ↓
Vues + logique métier (accounts / academics / exams / payments)
   ↓
MySQL
   ↓
Stockage (media) — PDF d'épreuves, logos écoles
   ↓
Contrôle d'accès serveur (gratuit vs Premium via Pass Semestre)
   ↓
Espace administrateur (Django Admin ou back-office dédié)
```

Contrairement à un outil interne, ArchivEx a une **surface publique large** : landing page, inscription, navigation académique et épreuves gratuites sont accessibles sans compte ou avec un compte gratuit. La surface d'attaque prioritaire est donc : (1) le contournement de la restriction Premium (accès direct aux PDF protégés par URL, manipulation du prix côté client), (2) l'authentification étudiante (inscription/connexion ouvertes à tous), (3) le flux de paiement et l'activation du Pass Semestre, et (4) l'upload et la diffusion des fichiers PDF.

---

# Méthodologie

## Passage 1 — Compréhension

Avant toute conclusion :

- analyser l'authentification et les comptes étudiants (`accounts`) ;
- analyser la structure académique École → Niveau → Filière → Année → Semestre → Matière (`academics`) ;
- analyser la gestion des épreuves et des fichiers PDF (`exams`) ;
- analyser la logique gratuit/Premium et le contrôle d'accès aux épreuves ;
- analyser le système de Pass Semestre et son activation ;
- analyser le module de paiement, même simulé (`payments`) ;
- analyser les favoris ;
- analyser la recherche et les filtres ;
- analyser l'espace administrateur et ses permissions ;
- analyser le stockage média (`media/`).

Ne conclure qu'après cette étape.

---

## Passage 2 — Audit

Chaque point reçoit obligatoirement un verdict :

- ✅ Conforme
- ❌ Vulnérable
- ⚠️ Partiel
- ⬜ Non applicable

Ne jamais regrouper plusieurs points.

---

# Checklist

## 1. Authentification étudiante

- Mot de passe hashé (jamais en clair), politique de complexité minimale
- Inscription limitée aux champs strictement nécessaires (prénom, nom, email, mot de passe, puis école/niveau/filière)
- Aucune route de dashboard, profil ou favoris accessible sans session valide
- Expiration de session raisonnable, déconnexion effective (invalidation de session)
- Protection contre le brute-force sur connexion et inscription (limitation de tentatives, throttling)
- Réinitialisation de mot de passe sécurisée (lien à usage unique, expiration courte, aucune fuite d'information sur l'existence d'un compte)

---

## 2. Base de données & modèles

- Validation des champs (email, montants, années, statuts) côté serveur, jamais uniquement côté client
- Contraintes d'unicité pertinentes (un favori unique par couple utilisateur/épreuve, un Pass actif cohérent par utilisateur/semestre)
- Index sur les colonnes de filtrage fréquent (matière, année, type, filière, semestre)
- Migrations propres, réversibles, testées
- Sauvegardes automatiques et testées (restauration) — critique pour les paiements et les accès

---

## 3. Contrôle d'accès gratuit / Premium (surface la plus critique)

- Le statut gratuit/Premium d'une matière ou d'une épreuve est déterminé **exclusivement côté serveur**, jamais par une donnée envoyée par le frontend
- Chaque vue servant un PDF vérifie, à chaque requête, si l'épreuve est gratuite OU si l'utilisateur dispose d'un Pass Semestre actif correspondant à cette épreuve (même école, niveau, filière, année, semestre)
- Impossible d'accéder à une épreuve protégée via une URL directe/devinée, un ID incrémental exposé sans vérification, ou en modifiant le JavaScript/l'affichage frontend
- Le masquage frontend (griser, flouter) n'est jamais la seule protection — il n'est qu'un affichage, la vérification réelle est côté serveur
- Un test explicite existe pour : utilisateur sans Pass → 403/redirection sur épreuve Premium ; utilisateur avec Pass → accès autorisé uniquement au périmètre couvert par son Pass

---

## 4. Système de Pass Semestre & activation d'accès

- Le prix du Pass est défini et lu **uniquement côté serveur** (table/service `Payment`/`Product`) — jamais transmis par le frontend, même à titre indicatif
- L'activation d'un accès (`semester_access` / equivalent) ne peut se produire qu'après confirmation serveur du paiement, jamais sur simple retour du frontend ("paiement réussi" côté JS)
- Un Pass est lié précisément à : utilisateur, école, niveau, filière, année académique, semestre — pas d'activation trop large par erreur de portée
- Impossible de créer ou modifier un accès directement en base sans passer par le flux de paiement/validation (hors action explicite et journalisée d'un administrateur)

---

## 5. Paiement (même en mode simulé/test)

- Toute transition d'état de paiement (`en_attente` → `réussi`/`échoué`/`annulé`) est pilotée par le serveur ou par un callback/webhook vérifié, jamais par un simple appel front annonçant le succès
- L'architecture de paiement est abstraite (service dédié) pour permettre l'ajout futur d'un fournisseur réel (Mobile Money, carte) sans réécrire la logique de déblocage
- Aucune clé/API de paiement en dur dans le code source, toujours via variables d'environnement
- Chaque paiement journalise : utilisateur, Pass concerné, montant, statut, date — les montants ne sont jamais recalculés à partir d'une valeur envoyée par le client
- Idempotence : un paiement confirmé deux fois (retry réseau, double clic) n'active pas deux accès ni ne facture deux fois

---

## 6. Gestion des épreuves & fichiers PDF

- Validation du type MIME réel du fichier uploadé (pas seulement l'extension `.pdf`)
- Limitation de la taille des fichiers uploadés
- Seul le staff autorisé (administrateur) peut créer/modifier/publier/dépublier une épreuve ou remplacer un PDF
- Une épreuve non publiée (`is_published = False`) n'est visible ni listée nulle part côté public, même via une URL directe
- Les fichiers protégés (Premium) ne sont jamais servis par une URL statique publique prévisible — ils passent par une vue Django qui vérifie les droits d'accès avant de streamer le fichier
- Nom de fichier et chemin de stockage non devinables (pas de titre en clair prévisible permettant d'énumérer les PDF)

---

## 7. Favoris

- Un utilisateur ne peut avoir qu'un seul favori pour une même épreuve (contrainte d'unicité `unique_together`)
- Les favoris ne sont visibles/modifiables que par leur propriétaire, jamais par un autre utilisateur (vérification de l'appartenance à chaque action)

---

## 8. Recherche & filtres

- Les requêtes de recherche sont paramétrées (ORM Django), jamais de SQL brut concaténé avec l'entrée utilisateur
- La recherche et les filtres ne doivent jamais devenir un moyen de lister ou déduire l'existence d'épreuves non publiées ou hors du périmètre de l'utilisateur
- Pagination systématique sur les résultats pour éviter les requêtes coûteuses et les fuites de volumétrie

---

## 9. Administration & gestion académique

- Toute route d'administration (Django Admin ou back-office dédié) exige une session staff valide, jamais un accès anonyme
- Séparation claire entre compte étudiant standard et compte administrateur — un étudiant ne doit jamais pouvoir accéder aux vues d'administration même en devinant l'URL
- Suppression d'une structure académique (école, niveau, filière, semestre, matière) déjà référencée par des épreuves : interdite ou fortement contrôlée (désactivation préférable à la suppression)
- L'administrateur peut désactiver un compte étudiant sans le supprimer, en conservant la traçabilité des paiements passés

---

## 10. API / endpoints (si exposés en JSON)

- Authentification obligatoire sur toute route exposant des données utilisateur, paiement ou accès
- Permissions vérifiées côté serveur à chaque endpoint, jamais uniquement côté client
- Pagination systématique sur les listes (épreuves, utilisateurs, paiements)
- Champs calculés (statut d'accès, prix) toujours en lecture seule côté serializer, jamais acceptés en entrée

---

## 11. Journal d'activité

- Paiements, activations de Pass, publications/dépublications d'épreuve, connexions administrateur : journalisés
- Journaux non modifiables a posteriori (append-only)
- Aucune donnée sensible en clair dans les logs (pas de mot de passe, pas de token de session, pas de détail de moyen de paiement)

---

## 12. Confidentialité des données étudiantes

- Les données personnelles d'un étudiant (email, filière, niveau) ne sont accessibles qu'à l'étudiant lui-même et aux rôles administrateurs autorisés
- Conservation des données limitée à ce qui est nécessaire (pas de profilage, pas de champ superflu au-delà de l'inscription simplifiée prévue)
- Les informations de paiement affichées à l'administrateur ne comprennent jamais de données de carte/moyen de paiement brutes (délégué au fournisseur de paiement futur)

---

## 13. Préparation évolutions futures

Vérifier que l'architecture permet d'ajouter, **sans casser l'existant** :

- Un vrai fournisseur de paiement (Mobile Money, carte) en remplacement du mode simulé
- L2, L3, Master, d'autres écoles et universités
- Corrigés, quiz, statistiques personnelles (V2)
- Gamification (XP, badges, classement) (V3)
- Fonctionnalités IA (génération d'exercices, explications) (V4)
- Une application mobile native (V6)

---

# Format des vulnérabilités

Pour chaque vulnérabilité :

- Gravité
- Emplacement
- Description
- Impact
- Scénario d'exploitation
- Correctif prêt à copier
- Temps estimé

---

# Rapport final

Le rapport doit contenir :

1. Évaluation globale (🔴 🟠 🟡 🟢)
2. Vulnérabilités critiques
3. Corrections rapides (< 10 minutes)
4. Plan de remédiation priorisé
5. Bonnes pratiques déjà présentes
6. Résumé complet de la checklist

---

# Principes de sécurité ArchivEx

- Le statut gratuit/Premium et le prix du Pass sont toujours déterminés côté serveur — jamais fournis ou modifiables par le frontend
- Un accès Premium n'est activé qu'après confirmation serveur du paiement, jamais sur simple retour frontend
- Les PDF protégés ne sont jamais exposés via une URL publique prévisible
- Toutes les vérifications de permissions (étudiant vs administrateur, gratuit vs Premium) sont effectuées côté serveur à chaque requête
- Pas de secrets (clés de paiement, identifiants MySQL, `SECRET_KEY`) dans le code source
- Services à responsabilité unique par app (`accounts`, `academics`, `exams`, `payments`)
- Journalisation sans fuite de données sensibles

Ce document est la référence de sécurité officielle du projet ArchivEx.
