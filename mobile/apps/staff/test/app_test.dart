import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';
import 'package:school_core/testing.dart';
import 'package:school_staff/app.dart';
import 'package:school_staff/data/staff_repository.dart';

import 'fake_api.dart';

const nbsp = ' ';

class Harness {
  Harness({bool live = false}) {
    api = ApiClient(baseUrl: 'http://testserver/api/v1/', client: MockClient(fake.call));
    auth = AuthService(api, store, requiredRole: 'STAFF');
    repository = StaffRepository(api);
    if (live) {
      realtime = () => RealtimeClient(
        api,
        socketUri('http://testserver/api/v1/'),
        channelFactory: (uri, headers) => channels[channels.length] = FakeChannel(),
        refresh: auth.refreshSession,
      );
    }
  }

  final fake = FakeApi();
  final store = MemoryTokenStore();
  final channels = <int, FakeChannel>{};
  late final ApiClient api;
  late final AuthService auth;
  late final StaffRepository repository;
  RealtimeClient Function()? realtime;

  Future<void> start(WidgetTester tester, {Size size = const Size(1080, 2400), double ratio = 2.6}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = ratio;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(StaffApp(auth: auth, repository: repository, realtime: realtime));
    await auth.restore();
    await tester.pumpAndSettle();
  }

  Future<void> login(WidgetTester tester, FakePerson who, {String? password}) async {
    await tester.enterText(find.byKey(const Key('login.identifier')), who.email);
    await tester.enterText(find.byKey(const Key('login.password')), password ?? who.password);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
  }

  Future<void> tab(WidgetTester tester, String label) async {
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)));
    await tester.pumpAndSettle();
  }
}

Future<Object?> caught(Future<Object?> future) async {
  try {
    await future;
    return null;
  } on Object catch (error) {
    return error;
  }
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('home: MY functions, the school day, notifications', (tester) async {
    final h = Harness();
    await h.start(tester);
    expect(find.text('School Managing'), findsOneWidget);
    await h.login(tester, h.fake.a);
    expect(find.text('Bonjour Clarisse'), findsOneWidget);
    expect(find.text('Économe'), findsOneWidget);
    expect(find.text('Bibliothécaire'), findsNothing); // B's function
    expect(find.text('2 séance(s) au planning'), findsOneWidget);
    expect(find.text('1 annulation(s)'), findsOneWidget);
    expect(find.text('Réunion du personnel'), findsOneWidget);
  });

  testWidgets('planning of the school (today / week) and recent changes', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Planning');
    expect(find.text('6e A · Mathématiques'), findsOneWidget);
    expect(find.text('Annulée'), findsOneWidget);
    expect(find.text('Séance annulée'), findsOneWidget);
    expect(find.textContaining('Sortie scolaire'), findsOneWidget);
    await tester.tap(find.text('Semaine'));
    await tester.pumpAndSettle();
    expect(find.text('5e B · Français'), findsOneWidget);
  });

  testWidgets('scan: the server gives staff NO solvency; MY passages only', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Portail');
    await tester.enterText(find.byKey(const Key('scan.token')), qrLea);
    await tester.pump();
    await tester.tap(find.byKey(const Key('scan.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Arrivée enregistrée'), findsOneWidget);
    expect(find.text('En retard (35 min)'), findsOneWidget);
    expect(find.text('Échéance dépassée'), findsNothing);
    expect(find.text('Scolarité à jour'), findsNothing);

    await h.tab(tester, 'Profil');
    await tester.tap(find.byKey(const Key('profile.scans')));
    await tester.pumpAndSettle();
    expect(find.text('Léa Mbarga'), findsWidgets);
    expect(find.text('Tom Ndiaye'), findsNothing); // another person's scan: never
  });

  testWidgets('my remuneration only; another payslip is a 404; no attendance API invented', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Profil');
    expect(find.textContaining('Matricule EMP-sa'), findsOneWidget);
    expect(find.textContaining('Pas encore disponible'), findsOneWidget); // staff attendance: no API yet
    await tester.tap(find.byKey(const Key('profile.pay')));
    await tester.pumpAndSettle();
    expect(find.text('Septembre 2026'), findsOneWidget);
    expect(find.text('185${nbsp}000 XAF'), findsOneWidget);
    await tester.tap(find.byKey(const Key('payslip.pay-a')));
    await tester.pumpAndSettle();
    expect(find.text('Salaire fixe'), findsOneWidget);
    expect(find.text('Correction'), findsOneWidget);
    expect(await caught(h.repository.payslip('pay-b')), isA<NotFoundException>());
  });

  testWidgets('wrong password, suspended account, account of another role', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a, password: 'mauvais-mot');
    expect(find.textContaining('Identifiant ou mot de passe incorrect'), findsOneWidget);
    h.fake.suspended.add('sa');
    await h.login(tester, h.fake.a);
    expect(find.textContaining('compte suspendu'), findsOneWidget);
    await h.login(tester, h.fake.parent); // a teacher account
    expect(find.textContaining('n\'est pas un compte personnel'), findsOneWidget);
    expect(h.auth.status, AuthStatus.signedOut);
  });

  testWidgets('B never sees A\'s data', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.b);
    expect(find.text('Bibliothécaire'), findsOneWidget);
    expect(find.text('Économe'), findsNothing);
    await h.tab(tester, 'Profil');
    await tester.tap(find.byKey(const Key('profile.pay')));
    await tester.pumpAndSettle();
    expect(find.text('Aucune paie validée pour le moment.'), findsOneWidget);
    expect(await caught(h.repository.payslip('pay-a')), isA<NotFoundException>());
  });

  testWidgets('live notification; 4401 expires; logout revokes', (tester) async {
    final h = Harness(live: true);
    await h.start(tester);
    await h.login(tester, h.fake.a);
    final socket = h.channels[0]!;
    socket.push({'type': 'auth.ok', 'membership': 'm-sa', 'unread_notifications': 3});
    await tester.pumpAndSettle();
    expect(find.text('3'), findsWidgets);
    h.fake.revokeAll();
    socket.closeWith(4401);
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedOut);
    expect(find.textContaining('session a expiré'), findsOneWidget);

    final again = Harness();
    await again.start(tester);
    await again.login(tester, again.fake.a);
    await again.tab(tester, 'Profil');
    await tester.tap(find.byKey(const Key('profile.logout')));
    await tester.pumpAndSettle();
    expect(find.text('Vous êtes déconnecté.'), findsOneWidget);
    expect(again.store.refreshToken, isNull);
  });

  testWidgets('communication: message to the administration; no complaints (parents and teachers only)', (
    tester,
  ) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Messages');
    expect(find.widgetWithText(Tab, 'Réclamations'), findsNothing);
    await tester.tap(find.widgetWithText(Tab, 'Messages'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('conversations.new')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('message.body')), 'Demande de congé le 12.');
    await tester.pump();
    await tester.tap(find.byKey(const Key('message.send')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('Demande de congé le 12.'), findsOneWidget);
    expect(h.fake.conversations.single['conversation_type'], 'ADMINISTRATION');
  });

  testWidgets('small phone (360 dp): every tab renders without overflow', (tester) async {
    final h = Harness();
    await h.start(tester, size: const Size(720, 1280), ratio: 2.0);
    await h.login(tester, h.fake.a);
    for (final label in ['Planning', 'Portail', 'Messages', 'Profil', 'Accueil']) {
      await h.tab(tester, label);
      expect(tester.takeException(), isNull, reason: label);
    }
  });

  testWidgets('forum: the school forum is offered (spaces decided by the server)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Messages');
    await tester.tap(find.widgetWithText(Tab, 'Forum'));
    await tester.pumpAndSettle();
    expect(find.text('Réunion de rentrée'), findsOneWidget);
    expect(find.text('Annonce'), findsOneWidget);
    expect(find.byKey(const Key('forum.new')), findsOneWidget); // a space where members may write
  });
}
