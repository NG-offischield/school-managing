/// Where the apps find the Django backend — ONE place for the four apps.
///
/// The address is given at build time, never written in the sources:
///
///   flutter run --dart-define-from-file=../../config/lan.json
///   `flutter run --dart-define=API_URL=http://<IPv4 du PC>:8000/api/v1/`
///
///   API_URL  REST base, e.g. http://192.168.1.10:8000/api/v1/   (required)
///   WS_URL   WebSocket, e.g. ws://192.168.1.10:8000/ws/v1/realtime/
///            (optional: derived from API_URL, same host and port)
///
/// The reference setup for phones is the PC's LAN address (Wi-Fi of the
/// box/router); 127.0.0.1 is only for `adb reverse` (USB) and 10.0.2.2 for
/// the emulator. See docs/reseau-local.md.
///
/// Guard rails (the bearer token travels with every request):
/// - clear-text http/ws only towards loopback, the emulator host or a
///   PRIVATE address (10/8, 172.16/12, 192.168/16, *.local), and never in a
///   release build: anything else must be https/wss;
/// - the WebSocket must point at the same host as the API.
library;

import 'package:flutter/foundation.dart';

class AppConfigException implements Exception {
  AppConfigException(this.message);

  final String message;

  @override
  String toString() => message;
}

class AppConfig {
  AppConfig._(this.api, this.socket);

  /// Reads the `--dart-define`s of the build.
  factory AppConfig.fromEnvironment() =>
      AppConfig.parse(apiUrl: const String.fromEnvironment('API_URL'), wsUrl: const String.fromEnvironment('WS_URL'));

  /// Validates [apiUrl] / [wsUrl]; throws [AppConfigException] with a French
  /// explanation shown by [ConfigErrorApp].
  factory AppConfig.parse({required String apiUrl, String wsUrl = '', bool release = kReleaseMode}) {
    final rawApi = apiUrl.trim();
    if (rawApi.isEmpty) {
      throw AppConfigException(
        'Adresse du serveur absente. Construisez l\'application avec '
        '--dart-define=API_URL=http://<IPv4 du PC>:8000/api/v1/ (voir docs/reseau-local.md).',
      );
    }
    final api = Uri.tryParse(rawApi.endsWith('/') ? rawApi : '$rawApi/');
    if (api == null || !api.hasScheme || api.host.isEmpty || !(api.scheme == 'http' || api.scheme == 'https')) {
      throw AppConfigException('API_URL invalide : « $rawApi ». Attendu : http(s)://hôte:port/api/v1/.');
    }
    if (api.scheme == 'http') _clearTextAllowed(api, 'API_URL', release);

    final rawWs = wsUrl.trim();
    final Uri socket;
    if (rawWs.isEmpty) {
      socket = api.replace(scheme: api.scheme == 'https' ? 'wss' : 'ws', path: '/ws/v1/realtime/', query: null);
    } else {
      final parsed = Uri.tryParse(rawWs.endsWith('/') ? rawWs : '$rawWs/');
      if (parsed == null || !(parsed.scheme == 'ws' || parsed.scheme == 'wss') || parsed.host.isEmpty) {
        throw AppConfigException('WS_URL invalide : « $rawWs ». Attendu : ws(s)://hôte:port/ws/v1/realtime/.');
      }
      if (parsed.host != api.host) {
        // The access token is sent in the handshake: never to another host.
        throw AppConfigException('WS_URL (${parsed.host}) doit viser le même serveur que API_URL (${api.host}).');
      }
      if (parsed.scheme == 'ws') {
        if (api.scheme == 'https') throw AppConfigException('API en https : le WebSocket doit être en wss.');
        _clearTextAllowed(parsed, 'WS_URL', release);
      }
      socket = parsed;
    }
    return AppConfig._(api, socket);
  }

  /// REST base, always ending with '/'.
  final Uri api;

  /// Live endpoint (ws/v1/realtime/).
  final Uri socket;

  String get apiUrl => api.toString();

  /// "192.168.1.10:8000" — shown on the sign-in screen to diagnose a LAN setup.
  String get serverLabel => api.hasPort ? '${api.host}:${api.port}' : api.host;

  static void _clearTextAllowed(Uri uri, String name, bool release) {
    if (release) {
      throw AppConfigException(
        '$name en clair (${uri.scheme}://) refusé dans une version publiée : utilisez https/wss.',
      );
    }
    if (!isPrivateHost(uri.host)) {
      throw AppConfigException(
        '$name en clair vers « ${uri.host} » refusé : le HTTP non chiffré n\'est permis que vers le réseau local '
        '(192.168.x.x, 10.x.x.x, 172.16-31.x.x), 127.0.0.1 ou 10.0.2.2.',
      );
    }
  }
}

/// Loopback, emulator host, RFC 1918 private IPv4, mDNS names.
bool isPrivateHost(String host) {
  final h = host.toLowerCase();
  if (h == 'localhost' || h.endsWith('.local')) return true;
  final parts = h.split('.');
  if (parts.length != 4) return false;
  final bytes = parts.map(int.tryParse).toList();
  if (bytes.any((b) => b == null || b < 0 || b > 255)) return false;
  final a = bytes[0]!, b = bytes[1]!;
  return a == 127 || a == 10 || (a == 172 && b >= 16 && b <= 31) || (a == 192 && b == 168);
}
