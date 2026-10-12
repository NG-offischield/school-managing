import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';
import 'package:school_teacher/app.dart';
import 'package:school_teacher/data/teacher_repository.dart';

import 'fake_api.dart';

class Harness {
  Harness() {
    api = ApiClient(baseUrl: 'http://testserver/api/v1/', client: MockClient(fake.call));
    auth = AuthService(api, store, requiredRole: 'TEACHER');
  }

  final fake = FakeApi();
  final store = MemoryTokenStore();
  late final ApiClient api;
  late final AuthService auth;

  Future<void> start(WidgetTester tester, {Widget Function(Widget app)? wrap}) async {
    tester.view.physicalSize = const Size(1080, 2400); // Pixel 7a class phone
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    final Widget app = TeacherApp(auth: auth, repository: TeacherRepository(api));
    await tester.pumpWidget(wrap == null ? app : wrap(app));
    await auth.restore();
    await tester.pumpAndSettle();
  }

  Future<void> login(WidgetTester tester, FakeTeacher who, {String? password}) async {
    await tester.enterText(find.byKey(const Key('login.identifier')), who.email);
    await tester.enterText(find.byKey(const Key('login.password')), password ?? who.password);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
  }
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  testWidgets('login -> dashboard with ONLY my data (isolation A / B)', (tester) async {
    final h = Harness();
    await h.start(tester);
    expect(find.text('School Managing'), findsOneWidget);
    await h.login(tester, h.fake.a);
    expect(find.text('Bonjour Jean'), findsOneWidget);
    await tester.scrollUntilVisible(find.text('Mes cours (2)'), 250);
    expect(find.text('Mes cours (2)'), findsOneWidget);
    expect(find.text('MATH — 6e A'), findsWidgets);
    // B's sessions and courses never appear, and no request ever names another teacher.
    expect(find.text('FR — 3e D'), findsNothing);
    expect(find.textContaining('Message pour Marie'), findsNothing);
    for (final request in h.fake.requests) {
      expect(request.url.queryParameters.containsKey('teacher'), isFalse);
      expect(request.url.toString(), isNot(contains('tb')));
    }
    await tester.scrollUntilVisible(find.text('Payée'), 250);
    expect(find.text('Rémunération du mois'), findsOneWidget);
    expect(find.text('45 000 XAF'), findsOneWidget);
    expect(h.store.refreshToken, isNotNull);
    expect(h.store.refreshToken, isNot(contains(h.fake.a.password)));
  });

  testWidgets('wrong password, suspended account, non-teacher account', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a, password: 'mauvais');
    expect(find.textContaining('Identifiant ou mot de passe incorrect'), findsOneWidget);
    h.fake.suspended.add('ta');
    await h.login(tester, h.fake.a);
    expect(find.textContaining('compte suspendu'), findsOneWidget);
    await h.login(tester, h.fake.parent);
    expect(find.textContaining('n\'est pas un compte enseignant'), findsOneWidget);
    expect(h.auth.status, AuthStatus.signedOut);
  });

  testWidgets('activation: code, password + confirmation, back to login; the code disappears', (tester) async {
    final h = Harness();
    await h.start(tester);
    await tester.tap(find.byKey(const Key('login.activate')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('activation.code')), 'MAUVAIS-CODE');
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.check')));
    await tester.pumpAndSettle();
    expect(find.textContaining('invalide, expiré ou déjà utilisé'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('activation.code')), h.fake.activationCode);
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.check')));
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Jean,'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('activation.password')), 'court');
    await tester.enterText(find.byKey(const Key('activation.confirmation')), 'autre');
    await tester.pump();
    expect(find.text('Les deux mots de passe ne sont pas identiques.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('activation.confirmation')), 'court');
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.complete')));
    await tester.pumpAndSettle();
    expect(find.textContaining('trop court'), findsOneWidget); // the server's password rule
    const chosen = 'Ardoise-Craie-2026!';
    await tester.enterText(find.byKey(const Key('activation.password')), chosen);
    await tester.enterText(find.byKey(const Key('activation.confirmation')), chosen);
    await tester.pump();
    await tester.tap(find.byKey(const Key('activation.complete')));
    await tester.pumpAndSettle();
    expect(find.text('Compte activé'), findsOneWidget);
    expect(find.textContaining(h.fake.activationCode), findsNothing); // never shown again
    await tester.tap(find.byKey(const Key('activation.toLogin')));
    await tester.pumpAndSettle();
    final identifier = tester.widget<TextField>(find.byKey(const Key('login.identifier')));
    expect(identifier.controller!.text, h.fake.a.email);
    await tester.enterText(find.byKey(const Key('login.password')), chosen);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Jean'), findsOneWidget);
  });

  testWidgets('planning (today / week), session detail, self check-in explained', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.tap(find.text('Planning').last);
    await tester.pumpAndSettle();
    expect(find.text('MATH — 6e A'), findsOneWidget);
    expect(find.text('MATH — 5e B'), findsOneWidget);
    expect(find.text('FR — 4e C'), findsNothing); // tomorrow
    await tester.tap(find.text('Semaine'));
    await tester.pumpAndSettle();
    expect(find.text('Vous remplacez Marie Ngo'), findsOneWidget);
    expect(find.text('Annulée'), findsWidgets);
    expect(find.text('FR — 3e D'), findsNothing); // B's session
    await tester.tap(find.text('FR — 4e C')); // tomorrow, I replace B: not started yet
    await tester.pumpAndSettle();
    expect(find.text('Salle'), findsOneWidget);
    expect(find.text('Enseignant remplacé'), findsOneWidget); // the session's changes
    await tester.tap(find.byKey(const Key('session.present')));
    await tester.pumpAndSettle();
    expect(find.textContaining('n\'a pas encore commencé'), findsOneWidget);
    Navigator.of(tester.element(find.byKey(const Key('session.present')))).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Aujourd\'hui').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('MATH — 6e A'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('session.present')));
    await tester.pumpAndSettle();
    expect(find.text('Présence déclarée. L\'administration la validera.'), findsOneWidget);
    expect(h.fake.checkIns, {'sa1': 'PRESENT'});
  });

  testWidgets('notifications: unread badge, read on open, all read', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    expect(find.text('1'), findsWidgets); // badge + dashboard metric
    await tester.tap(find.text('Messages'));
    await tester.pumpAndSettle();
    expect(find.text('Remplacement demain'), findsOneWidget);
    expect(find.text('Message pour Marie'), findsNothing);
    await tester.tap(find.text('Remplacement demain'));
    await tester.pumpAndSettle();
    expect(find.text('Vous remplacez Marie Ngo.'), findsOneWidget);
    expect(h.fake.notifications['ta']!.first['is_read'], isTrue);
    await tester.tapAt(const Offset(20, 100));
    await tester.pumpAndSettle();
    expect(find.text('Non lue'), findsNothing);
  });

  testWidgets('messages and complaints tabs open; a conversation keeps its live state (regression)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.tap(find.text('Messages'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(Tab, 'Messages')); // the conversations tab
    await tester.pumpAndSettle();
    await tester.tap(find.text('Devoirs de Awa'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull); // no ProviderNotFoundException
    expect(find.text('Bonjour, une question sur les devoirs.'), findsOneWidget);
    await tester.binding.handlePopRoute(); // system back
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(Tab, 'Réclamations'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('Aucune réclamation.'), findsOneWidget);
  });

  testWidgets('expired session goes back to login; logout; network errors are explained', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    h.fake.revokeAll(); // session revoked server-side (suspension, global logout...)
    await tester.tap(find.byTooltip('Actualiser').first);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('login.submit')), findsOneWidget);
    expect(find.textContaining('session a expiré'), findsOneWidget);
    expect(h.store.refreshToken, isNull);

    await h.login(tester, h.fake.a);
    h.fake.offline = true;
    await tester.tap(find.byTooltip('Actualiser').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('Connexion au serveur impossible'), findsOneWidget);
    expect(find.text('Réessayer'), findsOneWidget);
    h.fake.offline = false;
    await tester.tap(find.text('Réessayer'));
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Jean'), findsOneWidget);

    await tester.tap(find.text('Profil'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile.logout')));
    await tester.pumpAndSettle();
    expect(find.text('Vous êtes déconnecté.'), findsOneWidget);
    expect(h.store.refreshToken, isNull);
    expect(h.fake.tokens.values.where((p) => p.key == 'ta'), isEmpty); // revoked server-side too
  });

  testWidgets('remembered session resumes at start (refresh), small screen stays usable', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    final again = Harness()
      ..fake.refreshes.addAll(h.fake.refreshes)
      ..store.refreshToken = h.store.refreshToken;
    again.fake.tokens.clear();
    // Fresh app process: only the refresh token survived.
    tester.view.physicalSize = const Size(720, 1280); // small phone
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(TeacherApp(auth: again.auth, repository: TeacherRepository(again.api)));
    await again.auth.restore();
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Jean'), findsOneWidget);
    expect(tester.takeException(), isNull); // no overflow on a small screen
  });

  testWidgets('forum: the school forum is offered (spaces decided by the server)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Messages')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(Tab, 'Forum'));
    await tester.pumpAndSettle();
    expect(find.text('Réunion de rentrée'), findsOneWidget);
    expect(find.text('Annonce'), findsOneWidget);
    expect(find.byKey(const Key('forum.new')), findsOneWidget); // a space where members may write
  });

  Future<void> openComposer(WidgetTester tester, Harness h, FakeTeacher who) async {
    await h.start(tester);
    await h.login(tester, who);
    await tester.tap(find.descendant(of: find.byType(NavigationBar), matching: find.text('Messages')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(Tab, 'Messages'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('conversations.new')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('compose.parent')));
    await tester.pumpAndSettle();
  }

  testWidgets('teacher -> parent: only the parents the server offers, about one pupil', (tester) async {
    final h = Harness();
    await openComposer(tester, h, h.fake.a);
    expect(h.fake.requests.where((r) => r.url.path.endsWith('teacher/contacts/')), hasLength(1));
    expect(find.text('Awa Bella'), findsOneWidget);
    expect(find.text('Paul Parent'), findsOneWidget);
    expect(find.text('Père'), findsOneWidget);
    expect(find.text('Aucun parent vérifié.'), findsOneWidget); // Boris: nobody to write to
    await tester.enterText(find.byKey(const Key('contacts.filter')), 'bor');
    await tester.pumpAndSettle();
    expect(find.text('Awa Bella'), findsNothing); // the filter only narrows the server's list
    await tester.enterText(find.byKey(const Key('contacts.filter')), '');
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('message.body')), 'Bonjour, un point sur le devoir.');
    await tester.pumpAndSettle();
    final send = find.byKey(const Key('message.send'));
    expect(tester.widget<ButtonStyleButton>(send).onPressed, isNull); // no parent chosen yet
    await tester.tap(find.byKey(const Key('parent.s0.m-pa')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(send);
    await tester.tap(send);
    await tester.pumpAndSettle();
    expect(h.fake.started, hasLength(1));
    expect(h.fake.started.single['conversation_type'], 'PARENT_TEACHER');
    expect(h.fake.started.single['student'], 's0');
    expect(h.fake.started.single['participants'], ['m-pa']);
  });

  testWidgets('teacher -> parent: nobody to contact without pupils (server scope)', (tester) async {
    final h = Harness();
    await openComposer(tester, h, h.fake.b);
    expect(find.byKey(const Key('contacts.empty')), findsOneWidget);
    expect(find.text('Paul Parent'), findsNothing);
  });
}
