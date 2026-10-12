import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:school_parent/session.dart';
import 'package:school_parent/data/pdf_store.dart';
import 'package:school_core/school_core.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Server switch (school_core ServerHost): this app's session for one server
/// is left entirely — local session and saved documents of the old school.
void main() {
  test('leaving a server drops the session even when the old server is gone', () async {
    final asked = <String>[];
    final client = MockClient((request) async {
      asked.add(request.url.toString());
      throw http.ClientException('No route to host'); // the PC moved to another network
    });
    final tokens = MemoryTokenStore()..refreshToken = 'ref-old-school';
    final pdfs = MemoryPdfStore();
    await pdfs.save('recu.pdf', Uint8List.fromList(utf8.encode('%PDF old school')));
    final plans = MemoryPlanFiles();
    await plans.openPdf('plan.pdf', Uint8List.fromList(utf8.encode('%PDF old plan')));
    final session = parentSession(
      AppConfig.server('http://192.168.1.10:8000', release: false),
      client: client,
      tokens: tokens,
      pdfStore: pdfs,
      planFiles: plans,
    );
    await session.leave();
    expect(tokens.refreshToken, isNull);
    expect(pdfs.files, isEmpty);
    expect(plans.opened, isEmpty); // the old school's plans too
    expect(plans.cleared, 1);
    expect(asked, isEmpty); // no access token: nothing to revoke remotely, nothing sent
  });

  test('the session talks to the configured server only (REST + WebSocket from one address)', () async {
    final asked = <Uri>[];
    final client = MockClient((request) async {
      asked.add(request.url);
      return http.Response.bytes(
        utf8.encode(
          jsonEncode({
            'success': false,
            'error': {'code': 'NOT_AUTHENTICATED', 'message': 'x'},
          }),
        ),
        401,
        headers: {'content-type': 'application/json'},
      );
    });
    final config = AppConfig.server('http://10.0.0.20:8000', release: false);
    final session = parentSession(config, client: client, tokens: MemoryTokenStore()..refreshToken = 'ref');
    session.onReady!(); // restore: refresh against the configured server
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);
    expect(asked, isNotEmpty);
    expect(asked.every((u) => u.host == '10.0.0.20' && u.port == 8000), isTrue);
    expect(config.socket.toString(), 'ws://10.0.0.20:8000/ws/v1/realtime/');
  });

  test('leaving the server (sign-out, server switch) keeps the language and theme of this phone', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    SharedPreferences.setMockInitialValues({LanguageController.key: 'en', ThemeController.key: 'dark'});
    final session = parentSession(
      AppConfig.server('http://192.168.1.10:8000', release: false),
      client: MockClient((request) async => throw http.ClientException('gone')),
      tokens: MemoryTokenStore()..refreshToken = 'ref-old-school',
      planFiles: MemoryPlanFiles(), // never the real temporary folder in a test
      pdfStore: MemoryPdfStore(),
    );
    await session.leave();
    expect((await LanguageController.load()).language, AppLanguage.en);
    expect((await ThemeController.load()).mode, ThemeMode.dark);
  });
}
