/// Typed errors of the Django API (ADR 0007 envelope):
/// `{"success": false, "error": {"code", "message", "details": {"rule", ...}}}`.
///
/// The screens show [ApiException.userMessage]: the business rule explained
/// in French when it is known, otherwise the server's own message.
library;

import '../messages.dart';
import '../l10n/l10n.dart';

class ApiException implements Exception {
  ApiException({required this.status, required this.code, required this.message, this.details = const {}});

  final int status;
  final String code;
  final String message;
  final Map<String, dynamic> details;

  /// Stable business rule code (`details.rule`), e.g. `session_not_started`.
  String? get rule => details['rule'] as String?;

  /// Per-field messages of a VALIDATION_ERROR (`{"password": ["..."]}`).
  Map<String, List<String>> get fieldErrors {
    final result = <String, List<String>>{};
    details.forEach((key, value) {
      if (value is List) result[key] = value.map((e) => '$e').toList();
    });
    return result;
  }

  String get userMessage => explain(this);

  @override
  String toString() => 'ApiException($status $code${rule != null ? ' $rule' : ''})';
}

/// 401: missing / expired / revoked session, or wrong credentials.
class UnauthorizedException extends ApiException {
  UnauthorizedException({required super.code, required super.message, super.details}) : super(status: 401);
}

/// 403: no right (role, no active membership in the school...).
class ForbiddenException extends ApiException {
  ForbiddenException({required super.code, required super.message, super.details}) : super(status: 403);
}

/// 404: missing, or not visible to the caller (the server never says which).
class NotFoundException extends ApiException {
  NotFoundException({required super.code, required super.message, super.details}) : super(status: 404);
}

/// 409: conflicts with the current state.
class ConflictException extends ApiException {
  ConflictException({required super.code, required super.message, super.details}) : super(status: 409);
}

/// 400: invalid input or business rule.
class ValidationException extends ApiException {
  ValidationException({required super.code, required super.message, super.details}) : super(status: 400);
}

/// 429: too many attempts.
class RateLimitedException extends ApiException {
  RateLimitedException({required super.code, required super.message, super.details}) : super(status: 429);
}

/// 5xx: the server failed.
class ServerException extends ApiException {
  ServerException({required super.status, required super.code, required super.message}) : super();
}

/// No network / server unreachable / timeout: nothing was answered.
class NetworkException extends ApiException {
  NetworkException({this.timeout = false})
    : super(
        status: 0,
        code: timeout ? 'TIMEOUT' : 'NETWORK',
        message: timeout ? tr('Le serveur ne répond pas.') : tr('Connexion au serveur impossible.'),
      );

  final bool timeout;
}

ApiException errorFor(int status, Map<String, dynamic>? body) {
  final error = (body?['error'] as Map?)?.cast<String, dynamic>() ?? const {};
  final code = (error['code'] as String?) ?? 'HTTP_$status';
  final message = (error['message'] as String?) ?? tr('Erreur {0}', [status]);
  final details = (error['details'] as Map?)?.cast<String, dynamic>() ?? const <String, dynamic>{};
  switch (status) {
    case 400:
      return ValidationException(code: code, message: message, details: details);
    case 401:
      return UnauthorizedException(code: code, message: message, details: details);
    case 403:
      return ForbiddenException(code: code, message: message, details: details);
    case 404:
      return NotFoundException(code: code, message: message, details: details);
    case 409:
      return ConflictException(code: code, message: message, details: details);
    case 429:
      return RateLimitedException(code: code, message: message, details: details);
  }
  if (status >= 500) return ServerException(status: status, code: code, message: message);
  return ApiException(status: status, code: code, message: message, details: details);
}
