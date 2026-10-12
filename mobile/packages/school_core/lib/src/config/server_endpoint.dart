/// Which server the app talks to, chosen at RUNTIME (no rebuild when the
/// PC's address changes with the network), and the real reachability check.
///
/// Priority ([resolveServer]):
///   1. the address saved by the user (« Serveur » screen);
///   2. the build's initial value (`--dart-define` API_URL / WS_URL, lan.json);
///   3. none: the app opens on the server settings screen.
///
/// The address is not a secret and is stored as a plain preference
/// ([PreferencesEndpointStore]); tokens stay in the secure store, never here.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'app_config.dart';
import '../l10n/l10n.dart';

abstract class EndpointStore {
  Future<String?> read();
  Future<void> write(String address);
  Future<void> clear();
}

/// One preference per app ("school_managing.parent.server"), next to nothing else.
class PreferencesEndpointStore implements EndpointStore {
  PreferencesEndpointStore(String prefix) : key = '$prefix.server';

  final String key;

  @override
  Future<String?> read() async => (await SharedPreferences.getInstance()).getString(key);

  @override
  Future<void> write(String address) async => (await SharedPreferences.getInstance()).setString(key, address);

  @override
  Future<void> clear() async => (await SharedPreferences.getInstance()).remove(key);
}

class MemoryEndpointStore implements EndpointStore {
  MemoryEndpointStore([this.address]);

  String? address;

  @override
  Future<String?> read() async => address;

  @override
  Future<void> write(String value) async => address = value;

  @override
  Future<void> clear() async => address = null;
}

enum ServerSource { saved, build, none }

class ServerResolution {
  const ServerResolution(this.config, this.source, {this.warning, this.build});

  /// null = nothing usable: ask the user.
  final AppConfig? config;
  final ServerSource source;

  /// Why a saved or built-in address was not used (shown on the settings screen).
  final String? warning;

  /// The build's own address (to go back to it), when valid.
  final AppConfig? build;
}

/// [saved] first, then the build's `API_URL`/`WS_URL`, then nothing.
ServerResolution resolveServer({String? saved, String buildApiUrl = '', String buildWsUrl = '', bool? release}) {
  AppConfig? build;
  String? buildError;
  if (buildApiUrl.trim().isNotEmpty) {
    try {
      build = release == null
          ? AppConfig.parse(apiUrl: buildApiUrl, wsUrl: buildWsUrl)
          : AppConfig.parse(apiUrl: buildApiUrl, wsUrl: buildWsUrl, release: release);
    } on AppConfigException catch (error) {
      buildError = error.message;
    }
  }
  if (saved != null && saved.trim().isNotEmpty) {
    try {
      final config = release == null ? AppConfig.server(saved) : AppConfig.server(saved, release: release);
      return ServerResolution(config, ServerSource.saved, build: build);
    } on AppConfigException catch (error) {
      final warning = tr('Adresse enregistrée ignorée : {0}', [error.message]);
      if (build != null) return ServerResolution(build, ServerSource.build, warning: warning, build: build);
      return ServerResolution(null, ServerSource.none, warning: warning);
    }
  }
  if (build != null) return ServerResolution(build, ServerSource.build, build: build);
  return ServerResolution(null, ServerSource.none, warning: buildError);
}

enum ServerCheckKind { ok, unreachable, timeout, unexpected, invalidAddress, localNetworkDenied }

class ServerCheck {
  const ServerCheck(this.kind, this.message, {this.status});

  final ServerCheckKind kind;
  final String message;
  final int? status;

  bool get ok => kind == ServerCheckKind.ok;
}

/// `GET <api>/health/` — the backend's real health endpoint (public, no data).
/// Success only on HTTP 200 with the envelope {"success": true, "data": {"status": "ok"}}.
Future<ServerCheck> checkServer(
  AppConfig config, {
  http.Client? client,
  Duration timeout = const Duration(seconds: 6),
}) async {
  final http_ = client ?? http.Client();
  final url = config.api.resolve('health/');
  try {
    final response = await http_.get(url, headers: const {'Accept': 'application/json'}).timeout(timeout);
    if (response.statusCode == 200) {
      Object? body;
      try {
        body = jsonDecode(utf8.decode(response.bodyBytes));
      } on FormatException {
        body = null;
      }
      final data = body is Map ? body['data'] : null;
      if (body is Map && body['success'] == true && data is Map && data['status'] == 'ok') {
        return ServerCheck(
          ServerCheckKind.ok,
          tr('Serveur joignable : {0} répond.', [config.serverLabel]),
          status: 200,
        );
      }
      return ServerCheck(
        ServerCheckKind.unexpected,
        tr('Un service répond sur {0}, mais ce n\'est pas le serveur School Managing.', [config.serverLabel]),
        status: 200,
      );
    }
    if (response.statusCode == 400) {
      return ServerCheck(
        ServerCheckKind.unexpected,
        tr(
          'Le serveur refuse cette adresse (HTTP 400) : elle n\'est pas dans ses hôtes autorisés. Sur le PC, lancez mobile\\tools\\configure_lan.ps1 -Restart.',
        ),
        status: 400,
      );
    }
    return ServerCheck(
      ServerCheckKind.unexpected,
      tr('Réponse inattendue du serveur {0} : HTTP {1}.', [config.serverLabel, response.statusCode]),
      status: response.statusCode,
    );
  } on TimeoutException {
    return ServerCheck(
      ServerCheckKind.timeout,
      tr('Délai dépassé : {0} ne répond pas. Même Wi-Fi que le PC ? Pare-feu ? Serveur démarré ?', [
        config.serverLabel,
      ]),
    );
  } on SocketException {
    return ServerCheck(
      ServerCheckKind.unreachable,
      tr('Serveur inaccessible : {0} refuse ou ignore la connexion (adresse, port, Wi-Fi, pare-feu).', [
        config.serverLabel,
      ]),
    );
  } on http.ClientException {
    return ServerCheck(ServerCheckKind.unreachable, tr('Serveur inaccessible : {0}.', [config.serverLabel]));
  } finally {
    if (client == null) http_.close();
  }
}
