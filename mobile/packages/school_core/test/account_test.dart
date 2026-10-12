import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

/// « Mon compte » (school_core AccountScreen) against a fake server that
/// follows the contract of auth/me/profile/, auth/me/photo/, password and
/// sessions — field whitelist, per-field errors, photo rules. Widget tests,
/// not E2E.

final jpeg = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
);

http.Response json(Object? data, {int status = 200}) => http.Response.bytes(
  utf8.encode(jsonEncode({'success': status < 400, 'data': data, 'meta': {}})),
  status,
  headers: {'content-type': 'application/json'},
);

http.Response error(int status, String code, Map<String, dynamic> details) => http.Response.bytes(
  utf8.encode(
    jsonEncode({
      'success': false,
      'error': {'code': code, 'message': code, 'details': details},
    }),
  ),
  status,
  headers: {'content-type': 'application/json'},
);

class FakeAccountServer {
  FakeAccountServer({this.parent = true});

  final bool parent;
  final values = <String, String>{'phone': '', 'occupation': '', 'address': '', 'emergency_phone': ''};
  String language = 'fr';
  Uint8List? photo;
  final patches = <Map<String, dynamic>>[];
  final sessions = [
    {'id': 's1', 'device_name': 'Pixel 7a', 'platform': 'ANDROID', 'is_current': true},
    {'id': 's2', 'device_name': 'Tablette', 'platform': 'ANDROID', 'is_current': false},
  ];
  String password = 'Ancien-Mot-2026!';
  int revokedAll = 0;

  List<String> get editable =>
      parent ? ['phone', 'occupation', 'address', 'emergency_phone', 'preferred_language'] : ['phone'];

  Map<String, dynamic> profile() => {
    'first_name': 'Awa',
    'last_name': 'Mbarga',
    'email': 'awa@parents.test',
    'username': 'awa@parents.test',
    'phone': values['phone'],
    'has_photo': photo != null,
    'school_name': 'École Test',
    'roles': [parent ? 'PARENT' : 'GUARDIAN'],
    'parent': parent
        ? {
            'occupation': values['occupation'],
            'address': values['address'],
            'emergency_phone': values['emergency_phone'],
            'preferred_language': language,
          }
        : null,
    'employee': null,
    'editable': editable,
    'languages': parent ? {'fr': 'Français', 'en': 'Anglais'} : {},
  };

  Future<http.Response> call(http.Request request) async {
    final path = request.url.path.replaceFirst('/api/v1/', '');
    if (path == 'auth/me/profile/' && request.method == 'GET') return json(profile());
    if (path == 'auth/me/profile/' && request.method == 'PATCH') {
      final body = (jsonDecode(request.body) as Map).cast<String, dynamic>();
      patches.add(body);
      final forbidden = body.keys.where((k) => !editable.contains(k)).toList();
      if (forbidden.isNotEmpty) {
        return error(400, 'VALIDATION_ERROR', {
          for (final f in forbidden) f: ['Ce champ ne peut pas être modifié depuis votre profil.'],
        });
      }
      if ((body['phone'] as String?)?.contains(RegExp('[a-z]')) ?? false) {
        return error(400, 'VALIDATION_ERROR', {
          'phone': ['Numéro de téléphone invalide.'],
        });
      }
      body.forEach((k, v) => k == 'preferred_language' ? language = '$v' : values[k] = '$v');
      return json(profile());
    }
    if (path == 'auth/me/photo/') {
      switch (request.method) {
        case 'GET':
          return photo == null
              ? error(404, 'NOT_FOUND', {})
              : http.Response.bytes(photo!, 200, headers: {'content-type': 'image/jpeg'});
        case 'DELETE':
          photo = null;
          return json(profile());
      }
    }
    if (path == 'auth/password/change/') {
      final body = (jsonDecode(request.body) as Map).cast<String, dynamic>();
      if (body['current_password'] != password) {
        return error(400, 'VALIDATION_ERROR', {
          'current_password': ['Current password is incorrect.'],
        });
      }
      password = '${body['new_password']}';
      sessions.removeWhere((s) => s['is_current'] != true);
      return json(null);
    }
    if (path == 'auth/sessions/') return json(sessions);
    if (path.startsWith('auth/sessions/') && path.endsWith('/revoke/')) {
      sessions.removeWhere((s) => s['id'] == path.split('/')[2]);
      return json(null);
    }
    if (path == 'auth/sessions/revoke-all/') {
      revokedAll++;
      return json({'revoked_count': sessions.length});
    }
    if (path == 'auth/logout/') return json(null);
    return error(404, 'NOT_FOUND', {});
  }

  /// Multipart photo upload: the real content is checked server-side.
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is http.MultipartRequest) {
      final bytes = await request.files.single.finalize().toBytes();
      if (bytes.length < 8 || bytes[0] != 0x89) {
        final body = utf8.encode(
          jsonEncode({
            'success': false,
            'error': {
              'code': 'BUSINESS_RULE_VIOLATION',
              'message': 'x',
              'details': {'rule': 'photo_invalid'},
            },
          }),
        );
        return http.StreamedResponse(Stream.value(body), 400, headers: {'content-type': 'application/json'});
      }
      photo = Uint8List.fromList(bytes);
      final body = utf8.encode(jsonEncode({'success': true, 'data': profile()}));
      return http.StreamedResponse(Stream.value(body), 200, headers: {'content-type': 'application/json'});
    }
    final response = await call(request as http.Request);
    return http.StreamedResponse(Stream.value(response.bodyBytes), response.statusCode, headers: response.headers);
  }
}

class _Client extends http.BaseClient {
  _Client(this.server);

  final FakeAccountServer server;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is http.Request) return MockClient(server.call).send(request);
    return server.send(request);
  }
}

Future<AuthService> pump(WidgetTester tester, FakeAccountServer server, {ImageChooser? choose}) =>
    pumpAccountWith(tester, server, choose: choose);

/// « Mon compte » in a themed app ([theme] provided like main() does).
Future<AuthService> pumpAccountWith(
  WidgetTester tester,
  FakeAccountServer server, {
  ImageChooser? choose,
  ThemeController? theme,
}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.6;
  addTearDown(tester.view.reset);
  final api = ApiClient(baseUrl: 'http://h/api/v1/', client: _Client(server))..accessToken = 'acc';
  final auth = AuthService(api, MemoryTokenStore());
  final app = Builder(
    builder: (context) => MaterialApp(
      theme: buildAppTheme(),
      darkTheme: buildAppTheme(brightness: Brightness.dark),
      themeMode: themeModeOf(context),
      builder: themedScreens,
      locale: const Locale('fr', 'FR'),
      supportedLocales: const [Locale('fr', 'FR')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: AccountScreen(chooseImage: choose ?? () async => null),
    ),
  );
  await tester.pumpWidget(
    ChangeNotifierProvider<AuthService>.value(
      value: auth,
      child: theme == null ? app : ChangeNotifierProvider<ThemeController>.value(value: theme, child: app),
    ),
  );
  await tester.pumpAndSettle();
  return auth;
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('identity is read only; only the editable fields are offered, and only changes are sent', (tester) async {
    final server = FakeAccountServer();
    await pump(tester, server);
    expect(find.text('Awa Mbarga'), findsOneWidget);
    expect(find.text('Parent · École Test'), findsOneWidget);
    for (final f in ['phone', 'occupation', 'address', 'emergency_phone', 'preferred_language']) {
      expect(find.byKey(Key('account.field.$f')), findsOneWidget, reason: f);
    }
    expect(find.byKey(const Key('account.field.email')), findsNothing);
    await tester.enterText(find.byKey(const Key('account.field.phone')), '699 00 11 22');
    await tester.enterText(find.byKey(const Key('account.field.occupation')), 'Infirmière');
    await tester.ensureVisible(find.byKey(const Key('account.save')));
    await tester.tap(find.byKey(const Key('account.save')));
    await tester.pumpAndSettle();
    expect(server.patches.single, {'phone': '699 00 11 22', 'occupation': 'Infirmière'});
    expect(find.text('Coordonnées enregistrées.'), findsOneWidget);
  });

  testWidgets('a guardian edits only the phone; per-field server errors are shown', (tester) async {
    final server = FakeAccountServer(parent: false);
    await pump(tester, server);
    expect(find.byKey(const Key('account.field.address')), findsNothing);
    expect(find.text('Gardien · École Test'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('account.field.phone')), 'abc');
    await tester.tap(find.byKey(const Key('account.save')));
    await tester.pumpAndSettle();
    expect(find.text('Numéro de téléphone invalide.'), findsOneWidget);
    expect(find.text('Vérifiez les champs signalés.'), findsOneWidget);
  });

  testWidgets('photo: chosen, refused when unreadable, removed', (tester) async {
    final server = FakeAccountServer();
    var next = PickedImage(bytes: Uint8List.fromList(utf8.encode('MZ not an image')));
    await pump(tester, server, choose: () async => next);
    await tester.tap(find.byKey(const Key('account.photo.change')));
    await tester.pumpAndSettle();
    expect(find.text('Ce fichier n\'est pas une image lisible.'), findsOneWidget);
    expect(server.photo, isNull);
    next = PickedImage(bytes: jpeg);
    await tester.tap(find.byKey(const Key('account.photo.change')));
    await tester.pumpAndSettle();
    expect(server.photo, jpeg);
    expect(find.text('Photo mise à jour.'), findsOneWidget);
    expect(tester.widget<CircleAvatar>(find.byKey(const Key('account.avatar'))).foregroundImage, isNotNull);
    next = const PickedImage(error: 'too_large');
    await tester.tap(find.byKey(const Key('account.photo.change')));
    await tester.pumpAndSettle();
    expect(find.textContaining('dépasse 3 Mo'), findsOneWidget);
    await tester.tap(find.byKey(const Key('account.photo.remove')));
    await tester.pumpAndSettle();
    expect(server.photo, isNull);
    expect(tester.widget<CircleAvatar>(find.byKey(const Key('account.avatar'))).foregroundImage, isNull);
  });

  testWidgets('password: wrong current one explained, confirmation checked, success', (tester) async {
    final server = FakeAccountServer();
    await pump(tester, server);
    await tester.scrollUntilVisible(
      find.byKey(const Key('account.password')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('account.password')));
    await tester.pumpAndSettle();
    TextField field(String key) => tester.widget<TextField>(find.byKey(Key(key)));
    expect(field('password.new').obscureText, isTrue);
    await tester.tap(find.byKey(const Key('password.visibility')).first);
    await tester.pump();
    expect(field('password.new').obscureText, isFalse); // shown in clear on demand
    await tester.tap(find.byKey(const Key('password.visibility')).first);
    await tester.pump();
    expect(field('password.new').obscureText, isTrue);
    await tester.enterText(find.byKey(const Key('password.current')), 'faux');
    await tester.enterText(find.byKey(const Key('password.new')), 'Nouveau-Mot-2026!');
    await tester.enterText(find.byKey(const Key('password.confirm')), 'Autre');
    await tester.tap(find.byKey(const Key('password.submit')));
    await tester.pumpAndSettle();
    expect(find.textContaining('confirmation ne correspond pas'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('password.confirm')), 'Nouveau-Mot-2026!');
    await tester.tap(find.byKey(const Key('password.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Current password is incorrect.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('password.current')), 'Ancien-Mot-2026!');
    await tester.tap(find.byKey(const Key('password.submit')));
    await tester.pumpAndSettle();
    expect(server.password, 'Nouveau-Mot-2026!');
    expect(find.textContaining('autres appareils ont été déconnectés'), findsOneWidget);
  });

  testWidgets('sessions: this device cannot be revoked here; another can; revoke all signs out', (tester) async {
    final server = FakeAccountServer();
    final auth = await pump(tester, server);
    await tester.scrollUntilVisible(
      find.byKey(const Key('account.sessions')),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('account.sessions')));
    await tester.pumpAndSettle();
    expect(find.text('Cet appareil'), findsOneWidget);
    expect(find.byKey(const Key('session.revoke.s1')), findsNothing);
    await tester.tap(find.byKey(const Key('session.revoke.s2')));
    await tester.pumpAndSettle();
    expect(find.text('Tablette'), findsNothing);
    expect(find.textContaining('est déconnecté'), findsOneWidget);
    await tester.tap(find.byKey(const Key('sessions.revokeAll')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('sessions.revokeAll.confirm')));
    await tester.pumpAndSettle();
    expect(server.revokedAll, 1);
    expect(auth.signedIn, isFalse);
    expect(auth.api.accessToken, isNull);
  });
}
