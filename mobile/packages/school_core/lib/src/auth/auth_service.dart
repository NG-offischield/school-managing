/// Session of the connected person, built ONLY on the backend's sessions
/// (ADR 0002) — no local authentication:
///
///   login      POST /auth/login/  {identifier, password, device}
///   refresh    POST /auth/refresh/ {refresh_token}   (rotation; a reused token
///              revokes the session server-side)
///   logout     POST /auth/logout/
///   identity   GET  /auth/me/
///   activation POST /auth/activation/check/ {code}
///              POST /auth/activation/complete/ {code, password}   (ADR 0024)
///
/// The password is sent once and never kept. Only the refresh token is
/// stored (secure storage); the access token stays in memory.
library;

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/api_error.dart';
import 'identity.dart';
import 'token_store.dart';
import '../l10n/l10n.dart';

/// `pending`: signed in, but the account still waits for the school's approval
/// (self-registered parent, membership PENDING) — only apps created with
/// `allowPending` use it; the server grants nothing of the school meanwhile.
enum AuthStatus { restoring, signedOut, signedIn, pending }

class DeviceInfo {
  const DeviceInfo({
    this.name = 'Téléphone',
    this.type = 'PHONE',
    this.platform = 'ANDROID',
    this.appVersion = '0.1.0',
  });

  final String name;
  final String type;
  final String platform;
  final String appVersion;
}

class ActivationPreview {
  ActivationPreview({required this.firstName, required this.school, required this.login, this.expiresAt});

  final String firstName;
  final String school;
  final String login;
  final DateTime? expiresAt;
}

/// Login refused because this app is for another role (e.g. a parent
/// account opening the teacher app). The session is closed at once.
class WrongRoleException implements Exception {
  WrongRoleException(this.role);

  final String role;
}

class AuthService extends ChangeNotifier {
  AuthService(this.api, this.store, {this.device = const DeviceInfo(), this.requiredRole, this.allowPending = false}) {
    api.refreshHandler = _refreshQuietly;
  }

  final ApiClient api;
  final TokenStore store;
  final DeviceInfo device;

  /// Role the app is made for (e.g. TEACHER); null = any member.
  final String? requiredRole;

  /// Keep the session of an account whose membership is still PENDING
  /// (status [AuthStatus.pending]) instead of refusing it.
  final bool allowPending;

  AuthStatus status = AuthStatus.restoring;
  Identity? identity;

  /// Why the user is back on the login screen (expired session...).
  String? notice;

  bool get signedIn => status == AuthStatus.signedIn;

  /// Resume the remembered session, if any (app start).
  Future<void> restore() async {
    final refresh = await store.readRefreshToken();
    if (refresh == null) {
      _signedOut();
      return;
    }
    try {
      await _renew(refresh);
      await _loadIdentity();
    } on NetworkException {
      // Offline at start: keep the stored session, let the user retry.
      _signedOut(notice: tr('Serveur injoignable : vérifiez votre connexion puis reconnectez-vous.'));
      return;
    } on ApiException {
      await store.deleteRefreshToken();
      _signedOut(notice: tr('Votre session a expiré : reconnectez-vous.'));
    } on WrongRoleException {
      _signedOut(notice: tr('Ce compte n\'a pas accès à cette application.'));
    }
  }

  Future<void> login(String identifier, String password) async {
    final data =
        await api.post(
              'auth/login/',
              auth: false,
              body: {
                'identifier': identifier.trim(),
                'password': password,
                'device': {
                  'identifier': await store.deviceIdentifier(),
                  'device_name': device.name,
                  'device_type': device.type,
                  'platform': device.platform,
                  'app_version': device.appVersion,
                },
              },
            )
            as Map<String, dynamic>;
    await _keep(data);
    await _loadIdentity();
  }

  Future<ActivationPreview> checkActivation(String code) async {
    final data = await api.post('auth/activation/check/', auth: false, body: {'code': code.trim()}) as Map;
    return ActivationPreview(
      firstName: (data['first_name'] as String?) ?? '',
      school: (data['school'] as String?) ?? '',
      login: (data['login'] as String?) ?? '',
      expiresAt: DateTime.tryParse('${data['expires_at']}'),
    );
  }

  /// Sets the FIRST password (the server validates its strength and burns
  /// the code). Returns the login identifier to use.
  Future<String> completeActivation(String code, String password) async {
    final data =
        await api.post('auth/activation/complete/', auth: false, body: {'code': code.trim(), 'password': password})
            as Map;
    return (data['login'] as String?) ?? '';
  }

  /// Reload `/auth/me/` (e.g. the school approved a pending account).
  Future<void> reloadIdentity() => _loadIdentity();

  Future<void> logout() async {
    try {
      if (api.accessToken != null) await api.post('auth/logout/');
    } on ApiException {
      // Already revoked / offline: the local session is closed anyway.
    }
    await _clear();
    _signedOut(notice: tr('Vous êtes déconnecté.'));
  }

  /// The user switches to ANOTHER server: the old one is told if it still
  /// answers within [serverTimeout] (after a network change it usually does
  /// not), and the local session is dropped in every case — access token,
  /// identity, remembered refresh token. Nothing of the old school survives.
  Future<void> leaveServer({Duration serverTimeout = const Duration(seconds: 3)}) async {
    try {
      if (api.accessToken != null) await api.post('auth/logout/').timeout(serverTimeout);
    } catch (_) {
      // Unreachable, revoked or slow: the local session is closed anyway.
    }
    await _clear();
    _signedOut(notice: tr('Serveur changé : connectez-vous sur le nouveau serveur.'));
  }

  /// Session refused by the server (refresh failed, suspended account...).
  Future<void> expire([String? message]) async {
    await _clear();
    _signedOut(notice: message ?? tr('Votre session a expiré : reconnectez-vous.'));
  }

  /// One refresh of the access token (e.g. after the WebSocket was closed
  /// with 4401). A refused refresh expires the session.
  Future<bool> refreshSession() => _refreshQuietly();

  // --- internals ---------------------------------------------------------------------

  Future<void> _keep(Map<String, dynamic> tokens) async {
    api.accessToken = tokens['access_token'] as String?;
    await store.writeRefreshToken(tokens['refresh_token'] as String);
  }

  Future<void> _renew(String refresh) async {
    final data = await api.post('auth/refresh/', auth: false, body: {'refresh_token': refresh}) as Map<String, dynamic>;
    await _keep(data);
  }

  Future<bool> _refreshQuietly() async {
    final refresh = await store.readRefreshToken();
    if (refresh == null) return false;
    try {
      await _renew(refresh);
      return true;
    } on NetworkException {
      return false;
    } on ApiException {
      await expire();
      return false;
    }
  }

  Future<void> _loadIdentity() async {
    final me = Identity.fromMe((await api.get('auth/me/') as Map).cast<String, dynamic>());
    if (me.current == null) {
      if (allowPending && me.memberships.any((m) => m.status == 'PENDING')) {
        identity = me;
        notice = null;
        status = AuthStatus.pending;
        notifyListeners();
        return;
      }
      await _clear();
      throw ForbiddenException(code: 'NO_ACTIVE_MEMBERSHIP', message: tr('No active membership.'));
    }
    final role = requiredRole;
    if (role != null && !me.hasRole(role)) {
      try {
        await api.post('auth/logout/');
      } on ApiException {
        // ignore: the session is dropped locally anyway
      }
      await _clear();
      throw WrongRoleException(role);
    }
    identity = me;
    notice = null;
    status = AuthStatus.signedIn;
    notifyListeners();
  }

  Future<void> _clear() async {
    api.accessToken = null;
    identity = null;
    await store.deleteRefreshToken();
  }

  void _signedOut({String? notice}) {
    status = AuthStatus.signedOut;
    this.notice = notice;
    notifyListeners();
  }
}
