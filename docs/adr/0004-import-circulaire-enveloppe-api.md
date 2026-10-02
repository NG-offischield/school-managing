# ADR 0004 — Suppression du cycle d'import `common.api` ↔ DRF

- **Statut :** accepté — 2026-10-02
- **Contexte :** en Phase 1, `manage.py makemigrations` échouait avec `Could not import 'common.api.EnvelopeJSONRenderer'`.

## Origine exacte du cycle

1. Les settings DRF référencent `common.api.EnvelopeJSONRenderer` (`DEFAULT_RENDERER_CLASSES`), `common.api.EnvelopePagination` et `common.api.envelope_exception_handler`.
2. Un system check DRF lit `DEFAULT_PAGINATION_CLASS`, ce qui importe `common.api`.
3. `common.api` importait en tête `from rest_framework.views import exception_handler`.
4. `rest_framework/views.py`, ligne 108, déclare dans le **corps de la classe** `APIView` : `renderer_classes = api_settings.DEFAULT_RENDERER_CLASSES`. Ce setting est donc résolu au moment de l'import et ré-importe `common.api`.
5. `common.api` est alors à moitié initialisé dans `sys.modules` : `EnvelopeJSONRenderer` n'est pas encore défini et l'import échoue.

La dépendance responsable était `common.api → rest_framework.views`. Elle n'existait que pour le gestionnaire d'exceptions. Le renderer et la pagination n'en ont pas besoin.

## Décision

On sépare les deux responsabilités au lieu d'utiliser un import paresseux :

| Module | Contenu | Dépend de |
|---|---|---|
| `common/envelope.py` | renderer, pagination, `error_envelope`, `error_response` | `rest_framework.renderers`, `.pagination`, `.response`, qui ne résolvent pas `DEFAULT_RENDERER_CLASSES` à l'import |
| `common/exceptions.py` | `envelope_exception_handler` | `rest_framework.views` (import normal en tête) et `common.envelope` |

Importer `rest_framework.views` depuis `common.exceptions` déclenche l'import de `common.envelope`, qui est un **autre** module : il n'y a plus de cycle. Le setting `EXCEPTION_HANDLER` n'est résolu qu'au premier traitement d'exception, quand tout est déjà chargé.

**Aucun import paresseux n'est nécessaire.** Vérification faite dans les deux ordres : importer d'abord `common.envelope` puis d'abord `common.exceptions` fonctionne dans les deux cas.

## Règle pour la suite

Un module référencé par `DEFAULT_RENDERER_CLASSES`, `DEFAULT_PAGINATION_CLASS`, `DEFAULT_AUTHENTICATION_CLASSES` ou `DEFAULT_PERMISSION_CLASSES` ne doit jamais importer `rest_framework.views`, `rest_framework.generics` ni `rest_framework.viewsets`. Ce principe est rappelé dans la docstring de `common/envelope.py`.
