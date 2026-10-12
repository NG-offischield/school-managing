import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

/// School plans (backend documents/plans_api.py) in school_core: the reader
/// endpoints, the list / viewer screens (image zoom, PDF through the phone's
/// viewer), a PLAN notification, and the cleanup on a server switch.
/// Widget tests against a fake HTTP server — not E2E.

final png = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
);
final pdf = Uint8List.fromList(utf8.encode('%PDF-1.7 plan'));

http.Response ok(Object? data) => http.Response.bytes(
  utf8.encode(jsonEncode({'success': true, 'data': data, 'meta': {}})),
  200,
  headers: {'content-type': 'application/json'},
);

http.Response notFound() => http.Response.bytes(
  utf8.encode(
    jsonEncode({
      'success': false,
      'error': {'code': 'NOT_FOUND', 'message': 'Introuvable.'},
    }),
  ),
  404,
  headers: {'content-type': 'application/json'},
);

Map<String, dynamic> planJson(String id, String title, {String mime = 'image/png', String building = 'Bâtiment A'}) => {
  'id': id,
  'title': title,
  'description': 'Entrée principale au nord.',
  'building': building,
  'floor': 'RDC',
  'display_order': 0,
  'published_at': '2026-10-05T08:00:00+01:00',
  'school_name': 'Lycée Test',
  'version': {
    'number': 2,
    'mime_type': mime,
    'size_bytes': 1536,
    'width': mime == 'application/pdf' ? null : 1600,
    'height': mime == 'application/pdf' ? null : 1200,
    'page_count': mime == 'application/pdf' ? 3 : null,
    'published_at': '2026-10-05T08:00:00+01:00',
  },
  'file_url': '/api/v1/plans/$id/file/',
};

/// A fake server: [plans] by id; `gone` = withdrawn / no longer for me (404).
class FakeServer {
  FakeServer(this.plans);

  final Map<String, Map<String, dynamic>> plans;
  final gone = <String>{};
  final asked = <String>[];
  final headers = <Map<String, String>>[];

  ApiClient api() => ApiClient(
    baseUrl: 'http://h/api/v1/',
    client: MockClient((request) async {
      final path = request.url.path.replaceFirst('/api/v1/', '');
      asked.add(path);
      headers.add(request.headers);
      if (path == 'plans/') return ok([for (final p in plans.values) p]);
      if (path == 'notifications/') return ok(const []);
      final parts = path.split('/');
      final plan = plans[parts[1]];
      if (plan == null || gone.contains(parts[1])) return notFound();
      if (parts.length > 2 && parts[2] == 'file') {
        final mime = (plan['version'] as Map)['mime_type'] as String;
        return http.Response.bytes(mime == 'application/pdf' ? pdf : png, 200, headers: {'content-type': mime});
      }
      return ok(plan);
    }),
  )..accessToken = 'acc';
}

Future<void> pump(WidgetTester tester, Widget screen, CommunicationRepository repo, PlanFiles files) async {
  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider<LiveState>(create: (_) => LiveState()),
        Provider<CommunicationRepository>.value(value: repo),
        Provider<PlanFiles>.value(value: files),
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

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  test('reader endpoints: list, detail, bytes of the published version (authenticated)', () async {
    final server = FakeServer({'p1': planJson('p1', 'Plan général', mime: 'application/pdf')});
    final repo = CommunicationRepository(server.api());
    final rows = await repo.plans();
    final plan = rows.single;
    expect((plan.title, plan.location, plan.number, plan.isPdf), ('Plan général', 'Bâtiment A · RDC', 2, true));
    expect(plan.details, 'PDF · 3 pages · 2 Ko');
    expect(plan.publishedAt, DateTime(2026, 10, 5, 8));
    expect((await repo.plan('p1')).schoolName, 'Lycée Test');
    expect(await repo.planFile('p1'), pdf);
    expect(server.asked, ['plans/', 'plans/p1/', 'plans/p1/file/']);
    expect(server.headers.every((h) => h['Authorization'] == 'Bearer acc'), isTrue);
    server.gone.add('p1');
    await expectLater(repo.planFile('p1'), throwsA(isA<NotFoundException>()));
  });

  test('details of an image plan; sizes', () {
    final plan = SchoolPlan.fromJson(planJson('p', 'Cour'));
    expect((plan.isImage, plan.details), (true, 'PNG · 1600 × 1200 px · 2 Ko'));
    expect(sizeLabel(3 * 1024 * 1024 + 300 * 1024), '3,3 Mo');
  });

  test('a PLAN notification knows its plan, even once read; other types do not', () {
    final plan = AppNotification.fromJson({
      'id': 'n1',
      'notification_type': 'PLAN',
      'title': 'Plan publié : Plan général',
      'message': '',
      'payload': {'plan': 'p1', 'version': 'v2', 'number': 2},
    });
    expect((plan.planId, plan.typeLabel), ('p1', "Plan de l'établissement"));
    expect(plan.markedRead().planId, 'p1');
    final other = AppNotification.fromJson({
      'id': 'n2',
      'notification_type': 'MESSAGE',
      'payload': {'plan': 'p1'},
    });
    expect(other.planId, isNull);
  });

  testWidgets('list -> image plan: zoomable in memory, « ajuster » resets the zoom', (tester) async {
    final server = FakeServer({
      'p1': planJson('p1', 'Plan général'),
      'p2': planJson('p2', 'Annexe', mime: 'application/pdf', building: ''),
    });
    final files = MemoryPlanFiles();
    await pump(tester, const PlansScreen(), CommunicationRepository(server.api()), files);
    expect(find.text('Plan général'), findsOneWidget);
    expect(find.text('Annexe'), findsOneWidget);
    expect(find.text('Version 2 · publiée le 05/10/2026'), findsNWidgets(2));
    await tester.tap(find.text('Plan général'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('plan.image')), findsOneWidget);
    expect(find.text('Lycée Test · version 2 · publiée le 05/10/2026'), findsOneWidget);
    final viewer = tester.widget<InteractiveViewer>(find.byKey(const Key('plan.viewer')));
    expect((viewer.minScale, viewer.maxScale), (0.5, 8.0));
    viewer.transformationController!.value = Matrix4.diagonal3Values(3, 3, 1);
    await tester.tap(find.byKey(const Key('plan.fit')));
    await tester.pump();
    expect(viewer.transformationController!.value, Matrix4.identity());
    expect(files.opened, isEmpty); // an image never leaves the app's memory
    expect(server.asked, containsAllInOrder(['plans/', 'plans/p1/', 'plans/p1/file/']));
  });

  testWidgets('PDF plan: handed to the phone\'s viewer; no viewer = explained', (tester) async {
    final server = FakeServer({'p2': planJson('p2', 'Annexe', mime: 'application/pdf')});
    final files = MemoryPlanFiles();
    await pump(tester, const PlanViewerScreen(planId: 'p2'), CommunicationRepository(server.api()), files);
    expect(find.text('PDF · 3 pages · 2 Ko'), findsOneWidget);
    await tester.tap(find.byKey(const Key('plan.openPdf')));
    await tester.pumpAndSettle();
    expect(files.opened.keys.single, 'plan-Annexe-v2.pdf');
    expect(files.opened.values.single, pdf);
    expect(find.textContaining('lecteur PDF'), findsNothing);
    files.canOpen = false;
    await tester.tap(find.byKey(const Key('plan.openPdf')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Installez un lecteur PDF'), findsOneWidget);
  });

  testWidgets('a withdrawn plan / lost access: « plus disponible », nothing shown', (tester) async {
    final server = FakeServer({'p1': planJson('p1', 'Plan général')})..gone.add('p1');
    await pump(tester, const PlanViewerScreen(planId: 'p1'), CommunicationRepository(server.api()), MemoryPlanFiles());
    expect(find.textContaining("Ce plan n'est plus disponible"), findsOneWidget);
    expect(find.byKey(const Key('plan.image')), findsNothing);
  });

  testWidgets('no plan for me: an explicit empty state', (tester) async {
    await pump(tester, const PlansScreen(), CommunicationRepository(FakeServer({}).api()), MemoryPlanFiles());
    expect(find.text("Aucun plan de l'établissement n'est disponible pour le moment."), findsOneWidget);
  });

  testWidgets('PLAN notification: « Ouvrir le plan » opens the published plan', (tester) async {
    final server = FakeServer({'p1': planJson('p1', 'Plan général')});
    final notification = {
      'id': 'n1',
      'notification_type': 'PLAN',
      'severity': 'INFO',
      'title': 'Plan publié : Plan général',
      'message': 'Le plan « Plan général » est disponible.',
      'is_read': true,
      'created_at': '2026-10-05T08:00:00+01:00',
      'payload': {'plan': 'p1', 'version': 'v2', 'number': 2},
    };
    final api = ApiClient(
      baseUrl: 'http://h/api/v1/',
      client: MockClient((request) async {
        if (request.url.path.endsWith('notifications/')) return ok([notification]);
        return notFound();
      }),
    )..accessToken = 'acc';
    // Detail (JSON) and file (bytes) answered by the fake server.
    final repo = _SplitRepository(api, CommunicationRepository(server.api()));
    await pump(tester, const CommunicationScreen(messaging: false, complaints: false), repo, MemoryPlanFiles());
    await tester.tap(find.text('Plan publié : Plan général'));
    await tester.pumpAndSettle();
    expect(find.text("Plan de l'établissement"), findsOneWidget); // the type chip
    await tester.tap(find.byKey(const Key('notification.plan')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('plan.image')), findsOneWidget);
    expect(server.asked, ['plans/p1/', 'plans/p1/file/']);
  });

  test('server switch: the plans written for the viewer leave the phone', () async {
    TestWidgetsFlutterBinding.ensureInitialized();
    final root = await Directory.systemTemp.createTemp('plans_test');
    addTearDown(() => root.delete(recursive: true));
    final calls = <String>[];
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('school_core/local_network'),
      (call) async {
        calls.add(call.method);
        if (call.method == 'openDocument') {
          // The native side copies the file into cache/shared/ before we delete ours.
          expect(File(call.arguments['path'] as String).readAsBytesSync(), pdf);
          expect(call.arguments['mimeType'], 'application/pdf');
        }
        return true;
      },
    );
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger.setMockMethodCallHandler(
        const MethodChannel('school_core/local_network'),
        null,
      ),
    );
    final files = DevicePlanFiles(root: root);
    expect(await files.openPdf('plan/../général.pdf', pdf), isTrue);
    final folder = Directory('${root.path}/plans');
    expect(folder.listSync(), isEmpty); // the app's own copy is gone once handed over
    await files.clear();
    expect(folder.existsSync(), isFalse);
    expect(calls, ['openDocument', 'clearSharedDocuments']);
  });
}

/// Notifications from one client, plans from another (same contract).
class _SplitRepository extends CommunicationRepository {
  _SplitRepository(super.api, this.plansFrom);

  final CommunicationRepository plansFrom;

  @override
  Future<SchoolPlan> plan(String id) => plansFrom.plan(id);

  @override
  Future<Uint8List> planFile(String id) => plansFrom.planFile(id);
}
