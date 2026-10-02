# ADR 0007 — Format des erreurs API et internationalisation

- **Statut :** accepté — 2026-10-02 (décision du porteur du projet)

## Format

```json
{
  "success": false,
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Identifiants incorrects.",
    "details": { "...": "optionnel" }
  }
}
```

- **`code`** : stable, en anglais technique, jamais traduit. Les clients Flutter et PySide6 se basent sur lui ; renommer un code est un changement cassant. Le catalogue complet est `common.errors.ErrorCode`. Un test vérifie que chaque code a un message.
- **`message`** : texte destiné à l'utilisateur, localisable.
- **`details`** : présent seulement quand c'est utile, par exemple les erreurs par champ (`VALIDATION_ERROR`) ou `retry_after` (`RATE_LIMITED`).

Les succès gardent le format de la spec §6 : `{"success": true, "data": ..., "message": null, "meta": ...}`.

**Écart par rapport à la spec §6** : celle-ci décrit une enveloppe unique avec `message`. Les erreurs utilisent désormais l'objet `error` ci-dessus.

## Correspondance des exceptions

| Exception | Code | HTTP |
|---|---|---|
| `ValidationError` | `VALIDATION_ERROR` | 400 |
| `ParseError` | `PARSE_ERROR` | 400 |
| `NotAuthenticated` | `NOT_AUTHENTICATED` | 401 |
| access token invalide / session révoquée | `INVALID_ACCESS_TOKEN` | 401 |
| `AuthenticationFailed` (autre) | `AUTHENTICATION_FAILED` | 401 |
| login refusé | `INVALID_CREDENTIALS` | 401 |
| refresh refusé (inconnu, expiré, révoqué, réutilisé) | `INVALID_REFRESH_TOKEN` | 401 |
| `PermissionDenied` | `PERMISSION_DENIED` | 403 |
| aucune adhésion active | `NO_ACTIVE_MEMBERSHIP` | 403 |
| `NotFound` / `Http404` | `NOT_FOUND` | 404 |
| `MethodNotAllowed` | `METHOD_NOT_ALLOWED` | 405 |
| `Throttled` | `RATE_LIMITED` | 429 |
| toute exception non prévue | `SERVER_ERROR` | 500 |

**Erreur 500.** Elle renvoie du JSON, ne divulgue aucun détail interne et appelle `set_rollback()`. Sans cet appel, `ATOMIC_REQUESTS` commiterait le travail à moitié fait de la requête en échec. Un test le vérifie.

Les erreurs 401 utilisent des sous-classes d'`AuthenticationFailed` : DRF conserve alors le statut 401 et l'en-tête `WWW-Authenticate: Bearer` au lieu de les transformer en 403.

## Internationalisation

- Les chaînes source sont en **anglais**, selon la convention Django. **Le français est la langue par défaut de la V1** (`LANGUAGE_CODE = "fr"`). L'anglais est prêt (`LANGUAGES = fr, en`).
- Le client choisit la langue via `Accept-Language` (`LocaleMiddleware`). Une langue non prise en charge retombe sur le français.
- Les traductions sont dans `backend/locale/<lang>/LC_MESSAGES/django.po`. Les fichiers `.mo` compilés sont **versionnés**, parce que le code source est monté dans le conteneur et masquerait des `.mo` générés à la construction de l'image.
- Pour mettre à jour : `python manage.py makemessages -l fr -l en --ignore='tests/*'`, traduire, puis `python manage.py compilemessages`. `gettext` est installé dans l'image.
- Les messages de validation par champ sont déjà traduits par Django et DRF.
