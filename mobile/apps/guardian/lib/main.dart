import 'package:flutter/material.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';

import 'session.dart';

/// Backend address, never written in the sources (school_core AppConfig,
/// docs/reseau-local.md), by priority:
///   1. the server saved in the app (« Changer de serveur » / Profil → Serveur): no rebuild;
///   2. the build's initial value: flutter run --dart-define-from-file=../../config/lan.json
///      (or `--dart-define=API_URL=http://<IPv4 du PC>:8000/api/v1/`, optional WS_URL);
///   3. none: the app opens on the server settings screen.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await initializeDateFormatting('fr_FR');
  runApp(
    ServerHost(
      store: PreferencesEndpointStore('school_managing.guardian'),
      buildApiUrl: const String.fromEnvironment('API_URL'),
      buildWsUrl: const String.fromEnvironment('WS_URL'),
      session: guardianSession,
    ),
  );
}
