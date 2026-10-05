import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

http.Response ok(Object? data, {int status = 200}) => http.Response.bytes(
  utf8.encode(
    jsonEncode({
      'success': true,
      'data': data,
      'meta': {'count': 1, 'next': null},
    }),
  ),
  status,
  headers: {'content-type': 'application/json'},
);

ApiClient client(Future<http.Response> Function(http.Request) handler) =>
    ApiClient(baseUrl: 'http://h/api/v1/', client: MockClient(handler))..accessToken = 'acc';

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  test('gate: the scan answer is the server\'s; history reloads after each scan', () async {
    final api = client((request) async {
      if (request.url.path.endsWith('qr/scans/')) {
        return ok({
          'result': 'ACCEPTED',
          'scanned_at': '2026-10-05T07:40:00+01:00',
          'student': {'id': 's1', 'name': 'Léa', 'class': '6e A'},
          'attendance': {'status': 'PRESENT', 'late_minutes': 0},
          'solvency': null,
        }, status: 201);
      }
      expect(request.url.queryParameters['date'], isNotNull);
      return ok([
        {'id': 'x', 'result': 'UNKNOWN_TOKEN', 'scanned_at': '2026-10-05T07:00:00+01:00', 'student_name': null},
      ]);
    });
    final gate = GateRepository(api);
    var ticks = 0;
    gate.scans.addListener(() => ticks++);
    final outcome = await gate.scan('  QR  ');
    expect((outcome.accepted, outcome.studentName, outcome.solvency), (true, 'Léa', null));
    expect(ticks, 1);
    final rows = await gate.myScans(DateTime(2026, 10, 5));
    expect(rows.single.resultLabel, 'QR inconnu');
  });

  test('school calendar keeps the breaks still to come, soonest first', () async {
    final api = client(
      (_) async => ok([
        {
          'name': 'Plus tard',
          'break_type': 'HOLIDAY',
          'start_datetime': '2026-12-20T00:00:00+01:00',
          'end_datetime': '2027-01-04T00:00:00+01:00',
        },
        {
          'name': 'Passée',
          'break_type': 'EXAM',
          'start_datetime': '2026-01-01T00:00:00+01:00',
          'end_datetime': '2026-01-02T00:00:00+01:00',
        },
        {
          'name': 'Bientôt',
          'break_type': 'PUBLIC_HOLIDAY',
          'start_datetime': '2026-11-01T00:00:00+01:00',
          'end_datetime': '2026-11-01T23:00:00+01:00',
        },
      ]),
    );
    final breaks = await upcomingBreaks(api, now: DateTime(2026, 10, 5));
    expect(breaks.map((b) => b.name), ['Bientôt', 'Plus tard']);
    expect(breaks.first.typeLabel, 'Jour férié');
  });

  Future<void> pumpCommunication(WidgetTester tester, CommunicationScreen screen) async {
    final api = client((_) async => ok(<Object>[]));
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<LiveState>(create: (_) => LiveState()),
          Provider<CommunicationRepository>.value(value: CommunicationRepository(api)),
        ],
        child: MaterialApp(
          locale: const Locale('fr', 'FR'),
          supportedLocales: const [Locale('fr', 'FR')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          home: screen,
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('communication tabs follow the role (guardian: notifications only)', (tester) async {
    await pumpCommunication(tester, const CommunicationScreen(messaging: false, complaints: false));
    expect(find.byType(Tab), findsNothing);
    expect(find.text('Aucune notification.'), findsOneWidget);
    await pumpCommunication(tester, const CommunicationScreen(complaints: false));
    expect(find.widgetWithText(Tab, 'Messages'), findsOneWidget);
    expect(find.widgetWithText(Tab, 'Réclamations'), findsNothing);
    await pumpCommunication(tester, const CommunicationScreen());
    expect(find.byType(Tab), findsNWidgets(3));
  });
}
