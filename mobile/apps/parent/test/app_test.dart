import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:school_core/school_core.dart';
import 'package:school_parent/app.dart';
import 'package:school_parent/data/parent_repository.dart';
import 'package:school_parent/data/pdf_store.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'fake_api.dart';

const nbsp = ' '; // thousands separator of formatMoney

class Harness {
  Harness({bool live = false}) {
    api = ApiClient(baseUrl: 'http://testserver/api/v1/', client: MockClient(fake.call));
    auth = AuthService(api, store, requiredRole: 'PARENT', allowPending: true);
    repository = ParentRepository(api);
    if (live) {
      realtime = () => RealtimeClient(
        api,
        socketUri('http://testserver/api/v1/'),
        channelFactory: (uri, headers) {
          final channel = FakeChannel();
          channels.add(channel);
          return channel;
        },
        refresh: auth.refreshSession,
      );
    }
  }

  final fake = FakeApi();
  final store = MemoryTokenStore();
  final pdfs = MemoryPdfStore();
  final channels = <FakeChannel>[];
  late final ApiClient api;
  late final AuthService auth;
  late final ParentRepository repository;
  RealtimeClient Function()? realtime;

  Future<void> start(WidgetTester tester) async {
    tester.view.physicalSize = const Size(1080, 2400); // Pixel class phone
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(ParentApp(auth: auth, repository: repository, pdfStore: pdfs, realtime: realtime));
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

  Iterable<String> get paths => fake.requests.map((r) => r.url.toString());
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

  testWidgets('create my account -> pending approval -> approved -> home without child', (tester) async {
    final h = Harness();
    await h.start(tester);
    expect(find.text('School Managing'), findsOneWidget); // software identity on the login only
    await tester.tap(find.byKey(const Key('login.register')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('register.first_name')), 'Marie');
    await tester.enterText(find.byKey(const Key('register.last_name')), 'Ekane');
    await tester.enterText(find.byKey(const Key('register.email')), 'marie@parents.test');
    await tester.enterText(find.byKey(const Key('register.password')), 'court');
    await tester.enterText(find.byKey(const Key('register.confirmation')), 'court');
    await tester.pump();
    await tester.tap(find.byKey(const Key('register.submit')));
    await tester.pumpAndSettle();
    expect(find.textContaining('trop court'), findsOneWidget); // the server's password rules
    const strong = 'Marie-Ekane-2026!';
    await tester.enterText(find.byKey(const Key('register.password')), strong);
    await tester.enterText(find.byKey(const Key('register.confirmation')), strong);
    await tester.pump();
    await tester.tap(find.byKey(const Key('register.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Demande enregistrée'), findsOneWidget);
    await tester.tap(find.byKey(const Key('register.back')));
    await tester.pumpAndSettle();
    // The password was never kept: typed again at login.
    await tester.enterText(find.byKey(const Key('login.password')), strong);
    await tester.pump();
    await tester.tap(find.byKey(const Key('login.submit')));
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.pending);
    expect(find.textContaining('attend la validation'), findsOneWidget);
    expect(h.paths.where((p) => p.contains('parents/children')), isEmpty); // nothing of the school yet

    final me = h.fake.registered.single
      ..status = 'ACTIVE'
      ..roles = const ['PARENT'];
    h.fake.children[me.key] = [];
    await tester.tap(find.byKey(const Key('pending.check')));
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedIn);
    expect(find.text('Bonjour Marie'), findsOneWidget);
    expect(find.textContaining('Aucun enfant rattaché'), findsOneWidget);
  });

  testWidgets('wrong password, suspended account, non-parent account', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a, password: 'mauvais-mot');
    expect(find.textContaining('Identifiant ou mot de passe incorrect'), findsOneWidget);
    h.fake.suspended.add('pa');
    await h.login(tester, h.fake.a);
    expect(find.textContaining('compte suspendu'), findsOneWidget);
    await h.login(tester, h.fake.teacher);
    expect(find.textContaining('n\'est pas un compte parent'), findsOneWidget);
    expect(h.auth.status, AuthStatus.signedOut);
    expect(h.store.refreshToken, isNull);
  });

  testWidgets('home shows ONLY my children (A never sees B\'s child); another child is a 404', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    expect(find.text('Bonjour Awa'), findsOneWidget);
    expect(find.text('Mes enfants (2)'), findsOneWidget);
    expect(find.text('Léa Mbarga'), findsOneWidget);
    expect(find.text('6e A · 2026-2027'), findsOneWidget);
    expect(find.text('Tom Mbarga'), findsOneWidget);
    expect(find.textContaining('Zoé'), findsNothing);
    expect(find.textContaining('Retards répétés'), findsOneWidget); // convocation
    // The app never names a child it was not given by the server.
    expect(h.paths.where((p) => p.contains('c3')), isEmpty);
    expect(await caught(h.repository.attendance('c3')), isA<NotFoundException>());
    expect(await caught(h.repository.obligations('c3')), isA<NotFoundException>());
    expect(await caught(h.repository.teachers('c3')), isA<NotFoundException>());
    expect(h.store.refreshToken, isNot(contains(h.fake.a.password)));
  });

  testWidgets('attendance (never who scanned) and planning (today / week, changes)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Présences');
    expect(find.text('4.00 h'), findsOneWidget);
    expect(find.text('Alerte jaune'), findsOneWidget);
    expect(find.text('Entrée enregistrée'), findsOneWidget);
    expect(find.text('En retard'), findsOneWidget);
    expect(find.textContaining('15 min de retard'), findsOneWidget);
    expect(find.textContaining('Retards répétés'), findsWidgets);

    await h.tab(tester, 'Planning');
    expect(find.text('Mathématiques'), findsNWidgets(2));
    expect(find.text('Cours annulé'), findsOneWidget);
    expect(find.text('Enseignant remplaçant'), findsOneWidget);
    expect(find.textContaining('Jean Prof · Salle R12'), findsWidgets);
    await tester.tap(find.text('Semaine'));
    await tester.pumpAndSettle();
    expect(find.text('Cours annulé'), findsOneWidget);
    // Requests only ever target my selected child.
    final sessionCalls = h.paths.where((p) => p.contains('/sessions/'));
    expect(sessionCalls, isNotEmpty);
    expect(sessionCalls.every((p) => p.contains('students/c1/')), isTrue);
  });

  testWidgets('finance follows the rights granted by the school (can_view / can_pay)', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Finance');
    expect(find.text('40${nbsp}000 XAF'), findsWidgets); // amount from the server
    expect(find.text('Échéance dépassée'), findsOneWidget);
    expect(find.text('Paiement non autorisé pour votre compte'), findsOneWidget); // can_pay = false
    expect(find.textContaining('Payer'), findsNothing); // no payment from the app
    await tester.tap(find.byKey(const Key('receipt.pay1')));
    await tester.pumpAndSettle();
    expect(h.pdfs.files.keys, ['recu-PAY-0001.pdf']);

    // Tom: the link does not grant the financial data -> not even requested.
    await tester.tap(find.byKey(const Key('child.switcher')).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tom Mbarga').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('ne vous a pas donné accès'), findsOneWidget);
    expect(find.text('40${nbsp}000 XAF'), findsNothing);
    expect(h.paths.where((p) => p.contains('finance/students/c2')), isEmpty);
    // And the server refuses it anyway (defence in depth).
    expect(await caught(h.repository.obligations('c2')), isA<ForbiddenException>());
  });

  testWidgets('official report cards only, PDF download, authenticity check', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.scrollUntilVisible(find.byKey(const Key('home.documents')), 300);
    await tester.tap(find.byKey(const Key('home.documents')));
    await tester.pumpAndSettle();
    expect(find.text('Trimestre 1'), findsOneWidget);
    expect(find.textContaining('Moyenne 14.25 / 20.00'), findsOneWidget);
    await tester.tap(find.text('Trimestre 1'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('card.pdf.rc1')));
    await tester.pumpAndSettle();
    expect(h.pdfs.files.keys.single, startsWith('bulletin-MAT-c1'));
    expect(utf8.decode(h.pdfs.files.values.single), startsWith('%PDF'));

    await tester.tap(find.byKey(const Key('documents.verify')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('verify.code')), 'ABCD-1234');
    await tester.tap(find.text('Vérifier'));
    await tester.pumpAndSettle();
    expect(find.text('Document authentique : Bulletin T1.'), findsOneWidget);
  });

  testWidgets('link request (number + birth date + ID document), sponsor code, issuing a code', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await tester.tap(find.byKey(const Key('home.link')));
    await tester.pumpAndSettle();
    expect(find.text('Aucune demande.'), findsOneWidget);
    await tester.tap(find.byKey(const Key('link.new')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('link.number')), 'MAT-NEW');
    await tester.tap(find.byKey(const Key('link.birth')));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.edit_outlined)); // type the date
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '12/03/2015');
    await tester.tap(find.text('OK'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('link.document')), 'CM 1234-5678');
    await tester.pump();
    await tester.tap(find.byKey(const Key('link.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Nina Mbarga'), findsOneWidget);
    expect(find.text('À vérifier à l\'école'), findsOneWidget);
    final sent = h.fake.requests.lastWhere((r) => r.url.path.endsWith('parents/link-requests/') && r.method == 'POST');
    expect(jsonDecode(sent.body)['date_of_birth'], '2015-03-12');

    // A wrong sponsor code is refused by the server and explained.
    await tester.tap(find.byKey(const Key('link.sponsor.lr1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('sponsor.code')), 'AAAA-BBBB');
    await tester.tap(find.byKey(const Key('sponsor.submit')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Code de parrainage invalide'), findsOneWidget);

    // A verified parent issues a one-time code (shown once).
    await tester.scrollUntilVisible(find.byKey(const Key('sponsor.issue.c1')), 300);
    await tester.drag(find.byType(ListView).last, const Offset(0, -600)); // out from under the button
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('sponsor.issue.c1')));
    await tester.pumpAndSettle();
    expect(find.text('K7Q2-M9XA'), findsOneWidget);
    await tester.tap(find.text('Fermer'));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(find.byKey(const Key('link.sponsor.lr1')), -300);
    await tester.tap(find.byKey(const Key('link.sponsor.lr1')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('sponsor.code')), 'K7Q2-M9XA');
    await tester.tap(find.byKey(const Key('sponsor.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Vérifiée par parrainage'), findsOneWidget);
  });

  testWidgets('communication: notifications, writing to a teacher of my child, a complaint', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    await h.tab(tester, 'Messages');
    expect(find.text('Retard de Léa'), findsOneWidget);
    await tester.tap(find.widgetWithText(Tab, 'Messages'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('conversations.new')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Enseignant'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('teacher.m-tj')));
    await tester.enterText(find.byKey(const Key('message.body')), 'Bonjour, une question sur les devoirs.');
    await tester.pump();
    await tester.tap(find.byKey(const Key('message.send')));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('Bonjour, une question sur les devoirs.'), findsOneWidget); // the conversation opened
    final created = h.fake.conversations.single;
    expect((created['conversation_type'], created['student']), ('PARENT_TEACHER', 'c1'));
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(Tab, 'Réclamations'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('complaints.new')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('complaint.subject')), 'Cantine');
    await tester.enterText(find.byKey(const Key('complaint.description')), 'Repas froid.');
    await tester.pump();
    await tester.tap(find.byKey(const Key('complaint.submit')));
    await tester.pumpAndSettle();
    expect(find.text('Cantine'), findsOneWidget);
    expect(h.fake.complaints.single['student'], 'c1');
  });

  testWidgets('live: notification pushed on the WebSocket; refused socket (4401) expires the session', (tester) async {
    final h = Harness(live: true);
    await h.start(tester);
    await h.login(tester, h.fake.a);
    final socket = h.channels.single;
    socket.push({'type': 'auth.ok', 'membership': 'm-pa', 'unread_notifications': 2});
    await tester.pumpAndSettle();
    expect(find.text('2'), findsWidgets); // badge
    socket.push({
      'type': 'notification',
      'data': {
        'id': 'n9',
        'notification_type': 'CONVOCATION',
        'title': 'Convocation',
        'message': 'Jeudi 10 h',
        'is_read': false,
        'created_at': '2026-10-05T10:00:00+01:00',
      },
    });
    await tester.pumpAndSettle();
    expect(find.text('3'), findsWidgets);
    // The server closes the socket (session revoked): no refresh possible -> login.
    h.fake.revokeAll();
    socket.closeWith(4401);
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedOut);
    expect(find.textContaining('session a expiré'), findsOneWidget);
    expect(h.store.refreshToken, isNull);
  });

  testWidgets('expired session goes back to login; logout revokes; offline is explained', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    h.fake.revokeAll(); // access AND refresh refused
    await h.tab(tester, 'Planning');
    await tester.tap(find.text('Semaine'));
    await tester.pumpAndSettle();
    expect(h.auth.status, AuthStatus.signedOut);
    expect(find.textContaining('session a expiré'), findsOneWidget);

    await h.login(tester, h.fake.a);
    h.fake.offline = true;
    await h.tab(tester, 'Présences');
    await tester.tap(find.byKey(const Key('child.switcher')).first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tom Mbarga').last);
    await tester.pumpAndSettle();
    expect(find.textContaining('Connexion au serveur impossible'), findsOneWidget);
    h.fake.offline = false;
    await tester.tap(find.text('Réessayer'));
    await tester.pumpAndSettle();
    expect(find.text('Tom Mbarga'), findsOneWidget);

    await h.tab(tester, 'Accueil');
    await tester.tap(find.byKey(const Key('home.profile')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('profile.logout')));
    await tester.pumpAndSettle();
    expect(find.text('Vous êtes déconnecté.'), findsOneWidget);
    expect(h.store.refreshToken, isNull);
    expect(h.fake.tokens.values.where((p) => p.key == 'pa'), isEmpty); // revoked server-side too
  });

  testWidgets('small phone (360 dp): every tab renders without overflow; restored session', (tester) async {
    final h = Harness();
    await h.start(tester);
    await h.login(tester, h.fake.a);
    final again = Harness()
      ..fake.refreshes.addAll(h.fake.refreshes)
      ..store.refreshToken = h.store.refreshToken;
    tester.view.physicalSize = const Size(720, 1280);
    tester.view.devicePixelRatio = 2.0;
    await tester.pumpWidget(const SizedBox());
    await tester.pumpWidget(ParentApp(auth: again.auth, repository: again.repository, pdfStore: again.pdfs));
    await again.auth.restore(); // fresh process: only the refresh token survived
    await tester.pumpAndSettle();
    expect(find.text('Bonjour Awa'), findsOneWidget);
    for (final label in ['Présences', 'Planning', 'Finance', 'Messages', 'Accueil']) {
      await again.tab(tester, label);
      expect(tester.takeException(), isNull, reason: label);
    }
  });
}

class FakeChannel implements WebSocketChannel {
  final incoming = StreamController<dynamic>();
  final sent = <Map>[];
  int? code;
  late final _FakeSink _sink = _FakeSink(this);

  void push(Map frame) => incoming.add(jsonEncode(frame));

  void closeWith(int closeCode) {
    code = closeCode;
    incoming.close();
  }

  @override
  Stream get stream => incoming.stream;

  @override
  WebSocketSink get sink => _sink;

  @override
  int? get closeCode => code;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _FakeSink implements WebSocketSink {
  _FakeSink(this.channel);

  final FakeChannel channel;

  @override
  void add(dynamic data) => channel.sent.add(jsonDecode('$data') as Map);

  @override
  Future close([int? closeCode, String? closeReason]) async {}

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}
