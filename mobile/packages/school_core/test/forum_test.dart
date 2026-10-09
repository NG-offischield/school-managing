/// Shared forum screens (parent, teacher, staff) against an in-memory fake of
/// the EXISTING forum API: spaces, paginated threads and posts, announcements
/// (read-only), locked threads, my own posts, live refresh, errors.
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

const me = 'm-me';

http.Response _json(Object? data, {int status = 200, Map<String, dynamic>? meta}) => http.Response.bytes(
  utf8.encode(jsonEncode({'success': status < 400, 'data': data, 'meta': meta})),
  status,
  headers: {'content-type': 'application/json'},
);

http.Response _fail(int status, String code, {String? rule}) => http.Response.bytes(
  utf8.encode(
    jsonEncode({
      'success': false,
      'error': {
        'code': code,
        'message': code,
        'details': rule == null ? {} : {'rule': rule},
      },
    }),
  ),
  status,
  headers: {'content-type': 'application/json'},
);

class FakeForum {
  final spaces = <Map<String, dynamic>>[
    {'id': 'sp-school', 'name': 'Vie de l\'école', 'announcements_only': false},
    {'id': 'sp-news', 'name': 'Annonces', 'announcements_only': true},
  ];
  final threads = <Map<String, dynamic>>[];
  final posts = <String, List<Map<String, dynamic>>>{};
  final requests = <http.Request>[];

  Map<String, dynamic> thread(
    String id,
    String space,
    String title, {
    String type = 'GENERAL',
    String status = 'OPEN',
    String? reason,
  }) {
    final row = {
      'id': id,
      'space': space,
      'title': title,
      'thread_type': type,
      'status': status,
      'status_reason': reason,
      'author_name': 'Clarisse Admin',
      'created_at': '2026-10-08T08:00:00+01:00',
      'last_post_at': '2026-10-08T08:00:00+01:00',
    };
    threads.add(row);
    posts[id] = [];
    return row;
  }

  Map<String, dynamic> post(String thread, String body, {String author = 'm-other', String name = 'Awa Mbarga'}) {
    final row = {
      'id': 'p${posts.values.fold<int>(0, (n, l) => n + l.length) + 1}',
      'thread': thread,
      'author': author,
      'author_name': name,
      'post_type': 'MESSAGE',
      'body': body,
      'created_at': '2026-10-08T09:00:00+01:00',
      'deleted_at': null,
      'deletion_reason': null,
    };
    posts[thread]!.add(row);
    return row;
  }

  http.Response _page(List<Map<String, dynamic>> rows, Map<String, String> params, int size) {
    final page = int.parse(params['page'] ?? '1');
    final pageSize = int.parse(params['page_size'] ?? '$size');
    final slice = rows.skip((page - 1) * pageSize).take(pageSize).toList();
    final hasNext = page * pageSize < rows.length;
    return _json(slice, meta: {'count': rows.length, 'next': hasNext ? 'more' : null});
  }

  Future<http.Response> call(http.Request request) async {
    requests.add(request);
    final path = request.url.path.replaceFirst('/api/v1/', '');
    final params = request.url.queryParameters;
    final body = request.body.isEmpty ? <String, dynamic>{} : (jsonDecode(request.body) as Map).cast<String, dynamic>();
    if (path == 'auth/login/') {
      return _json({'access_token': 'acc', 'refresh_token': 'ref', 'access_expires_in': 900});
    }
    if (path == 'auth/me/') {
      return _json({
        'id': 'u-me',
        'username': 'parent@demo.test',
        'first_name': 'Awa',
        'last_name': 'Mbarga',
        'memberships': [
          {
            'id': me,
            'school_code': 'DEMO',
            'school_name': 'Démo',
            'status': 'ACTIVE',
            'is_primary_school': true,
            'roles': ['PARENT'],
          },
        ],
      });
    }
    if (path == 'notifications/') return _json(<Object>[], meta: {'count': 0, 'next': null});
    if (path == 'forum/spaces/') return _json(spaces);
    if (path == 'forum/threads/' && request.method == 'POST') {
      final space = spaces.firstWhere((s) => s['id'] == body['space']);
      if (space['announcements_only'] == true) return _fail(403, 'PERMISSION_DENIED');
      final row = thread('t${threads.length + 1}', '${body['space']}', '${body['title']}');
      post(row['id'] as String, '${body['body']}', author: me, name: 'Awa Mbarga');
      return _json(row, status: 201);
    }
    if (path == 'forum/threads/') {
      final space = params['space'];
      return _page(threads.where((t) => space == null || t['space'] == space).toList(), params, 20);
    }
    final match = RegExp(r'^forum/threads/([^/]+)/(posts/)?$').firstMatch(path);
    if (match != null) {
      final row = threads.where((t) => t['id'] == match[1]).firstOrNull;
      if (row == null) return _fail(404, 'NOT_FOUND');
      if (match[2] == null) return _json(row);
      if (request.method == 'POST') {
        if (row['thread_type'] == 'ANNOUNCEMENT') return _fail(403, 'PERMISSION_DENIED');
        if (row['status'] != 'OPEN') return _fail(409, 'CONFLICT', rule: 'thread_locked'); // CONFLICT_RULES
        return _json(post(row['id'] as String, '${body['body']}', author: me, name: 'Awa Mbarga'), status: 201);
      }
      return _page(posts[row['id']]!, params, 30);
    }
    final delete = RegExp(r'^forum/posts/([^/]+)/$').firstMatch(path);
    if (delete != null && request.method == 'DELETE') {
      final row = posts.values.expand((l) => l).firstWhere((p) => p['id'] == delete[1]);
      if (row['author'] != me) return _fail(403, 'PERMISSION_DENIED');
      row['deleted_at'] = '2026-10-08T10:00:00+01:00';
      row['body'] = null;
      return _json(row);
    }
    return _fail(404, 'NOT_FOUND');
  }

  int count(String method, String path) =>
      requests.where((r) => r.method == method && r.url.path.endsWith(path)).length;
}

void main() {
  setUpAll(() => initializeDateFormatting('fr_FR'));

  late FakeForum fake;
  late LiveState live;

  Future<void> pump(WidgetTester tester, {bool forum = true, Size size = const Size(1080, 2400)}) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 2.6;
    addTearDown(tester.view.reset);
    final api = ApiClient(baseUrl: 'http://h/api/v1/', client: MockClient(fake.call));
    final auth = AuthService(api, MemoryTokenStore());
    await auth.login('parent@demo.test', 'x');
    live = LiveState();
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthService>.value(value: auth),
          ChangeNotifierProvider<LiveState>.value(value: live),
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
          home: CommunicationScreen(forum: forum),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  Future<void> openForum(WidgetTester tester) async {
    await tester.tap(find.widgetWithText(Tab, 'Forum'));
    await tester.pumpAndSettle();
  }

  setUp(() {
    fake = FakeForum();
    fake.thread('t-ann', 'sp-news', 'Réunion des parents', type: 'ANNOUNCEMENT');
    fake.post('t-ann', 'Vendredi 17 h.', author: 'm-admin', name: 'Clarisse Admin');
    fake.thread('t-car', 'sp-school', 'Covoiturage du mercredi');
    fake.post('t-car', 'Des parents du quartier ?');
    fake.thread('t-lock', 'sp-school', 'Ancienne discussion', status: 'LOCKED', reason: 'Hors sujet');
  });

  testWidgets('the forum tab exists only when the role has it (guardian: none)', (tester) async {
    await pump(tester, forum: false);
    expect(find.widgetWithText(Tab, 'Forum'), findsNothing);
    expect(fake.count('GET', 'forum/spaces/'), 0); // not even asked
    await pump(tester);
    expect(find.widgetWithText(Tab, 'Forum'), findsOneWidget);
  });

  testWidgets('list: my spaces, discussions, announcement and locked badges', (tester) async {
    await pump(tester);
    await openForum(tester);
    expect(find.byKey(const Key('forum.space.sp-school')), findsOneWidget);
    expect(find.text('Réunion des parents'), findsOneWidget);
    expect(find.text('Covoiturage du mercredi'), findsOneWidget);
    expect(find.text('Annonce'), findsOneWidget);
    expect(find.text('Verrouillé'), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('forum.space.sp-news'))); // chips scroll sideways
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('forum.space.sp-news')));
    await tester.pumpAndSettle();
    expect(find.text('Covoiturage du mercredi'), findsNothing);
    expect(fake.requests.last.url.queryParameters['space'], 'sp-news');
  });

  testWidgets('no space open to me: explained, no new topic', (tester) async {
    fake.spaces.clear();
    await pump(tester);
    await openForum(tester);
    expect(find.textContaining('Aucun espace de forum'), findsOneWidget);
    expect(find.byKey(const Key('forum.new')), findsNothing);
  });

  testWidgets('pagination: the next discussions on demand', (tester) async {
    for (var i = 0; i < 25; i++) {
      fake.thread('t-p$i', 'sp-school', 'Sujet $i');
    }
    await pump(tester);
    await openForum(tester);
    await tester.scrollUntilVisible(
      find.byKey(const Key('forum.more')),
      300,
      scrollable: find.descendant(of: find.byKey(const Key('forum.threads')), matching: find.byType(Scrollable)).first,
    );
    await tester.drag(find.byKey(const Key('forum.threads')), const Offset(0, -400)); // above the FAB
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('forum.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('forum.more')), findsNothing);
    final asked = fake.requests
        .where((r) => r.url.path.endsWith('forum/threads/'))
        .map((r) => r.url.queryParameters['page']);
    expect(asked, containsAllInOrder(['1', '2']));
  });

  testWidgets('a discussion: posts, a reply, my post can be removed', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.text('Covoiturage du mercredi'));
    await tester.pumpAndSettle();
    expect(find.text('Des parents du quartier ?'), findsOneWidget);
    expect(find.byIcon(Icons.delete_outline), findsNothing); // not my post
    await tester.enterText(find.byKey(const Key('forum.reply')), 'Moi, le mercredi matin.');
    await tester.pump();
    await tester.tap(find.byKey(const Key('forum.send')));
    await tester.pumpAndSettle();
    expect(find.text('Moi, le mercredi matin.'), findsOneWidget);
    expect(fake.count('POST', 'forum/threads/t-car/posts/'), 1);

    final mine = fake.posts['t-car']!.last['id'];
    await tester.tap(find.byKey(Key('forum.delete.$mine')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('forum.delete.confirm')));
    await tester.pumpAndSettle();
    expect(find.text('Message retiré.'), findsOneWidget);
  });

  testWidgets('announcement: read-only, no reply box', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.text('Réunion des parents'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('forum.announcement')), findsOneWidget);
    expect(find.byKey(const Key('forum.reply')), findsNothing);
    expect(find.text('Vendredi 17 h.'), findsOneWidget);
  });

  testWidgets('locked discussion: reason shown, no reply box', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.text('Ancienne discussion'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Hors sujet'), findsOneWidget);
    expect(find.byKey(const Key('forum.reply')), findsNothing);
  });

  testWidgets('locked while I was writing: the server refusal is explained and the thread reloaded', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.text('Covoiturage du mercredi'));
    await tester.pumpAndSettle();
    fake.threads.firstWhere((t) => t['id'] == 't-car')['status'] = 'LOCKED';
    await tester.enterText(find.byKey(const Key('forum.reply')), 'Trop tard ?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('forum.send')));
    await tester.pumpAndSettle();
    expect(find.textContaining('verrouillée'), findsWidgets);
    expect(find.byKey(const Key('forum.reply')), findsNothing);
  });

  testWidgets('new topic in a space where I may write (not in announcements)', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.byKey(const Key('forum.new')));
    await tester.pumpAndSettle();
    // Only the writable space is offered (the announcements space is not).
    await tester.tap(find.byKey(const Key('forum.new.space')));
    await tester.pumpAndSettle();
    expect(find.text('Annonces'), findsNothing);
    await tester.tap(find.text('Vie de l\'école').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('forum.new.title')), 'Sortie au musée');
    await tester.enterText(find.byKey(const Key('forum.new.body')), 'Qui accompagne ?');
    await tester.pump();
    await tester.tap(find.byKey(const Key('forum.new.submit')));
    await tester.pumpAndSettle();
    // The new discussion opens.
    expect(find.text('Qui accompagne ?'), findsOneWidget);
    expect(fake.threads.last['title'], 'Sortie au musée');
  });

  testWidgets('only announcement spaces: no new topic button', (tester) async {
    fake.spaces.removeWhere((s) => s['announcements_only'] == false);
    await pump(tester);
    await openForum(tester);
    expect(find.byKey(const Key('forum.new')), findsNothing);
  });

  testWidgets('a discussion that no longer exists (404): explained, retry', (tester) async {
    await pump(tester);
    await openForum(tester);
    fake.threads.removeWhere((t) => t['id'] == 't-car');
    await tester.tap(find.text('Covoiturage du mercredi'));
    await tester.pumpAndSettle();
    expect(find.textContaining('n\'existe plus'), findsOneWidget);
    expect(find.byKey(const Key('forum.retry')), findsOneWidget);
  });

  testWidgets('live: a forum notification refreshes the open discussion', (tester) async {
    await pump(tester);
    await openForum(tester);
    await tester.tap(find.text('Covoiturage du mercredi'));
    await tester.pumpAndSettle();
    fake.post('t-car', 'Réponse arrivée pendant la lecture', name: 'Prof Mbida');
    live.notifications.add({
      'id': 'n1',
      'notification_type': 'FORUM',
      'title': 'Nouvelle réponse',
      'message': '…',
      'payload': {'thread': 't-car', 'space': 'sp-school'},
      'is_read': false,
      'created_at': '2026-10-08T10:00:00+01:00',
    });
    await tester.pumpAndSettle();
    expect(find.text('Réponse arrivée pendant la lecture'), findsOneWidget);
  });

  testWidgets('a forum notification opens its discussion', (tester) async {
    await pump(tester);
    live.notifications.add({
      'id': 'n2',
      'notification_type': 'ANNOUNCEMENT',
      'title': 'Réunion des parents',
      'message': 'Vendredi 17 h.',
      'payload': {'thread': 't-ann', 'space': 'sp-news'},
      'is_read': true,
      'created_at': '2026-10-08T10:00:00+01:00',
    });
    await tester.pumpAndSettle();
    await tester.tap(find.text('Réunion des parents'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('notification.thread')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('forum.announcement')), findsOneWidget);
    expect(find.text('Vendredi 17 h.'), findsOneWidget);
  });

  testWidgets('pull to refresh asks the server again', (tester) async {
    await pump(tester);
    await openForum(tester);
    final before = fake.count('GET', 'forum/threads/');
    await tester.fling(find.byKey(const Key('forum.threads')), const Offset(0, 400), 1000);
    await tester.pumpAndSettle();
    expect(fake.count('GET', 'forum/threads/'), greaterThan(before));
  });

  testWidgets('small phone (360 dp): forum, discussion and new topic fit', (tester) async {
    await pump(tester, size: const Size(720, 1280));
    tester.view.devicePixelRatio = 2.0;
    await tester.pumpAndSettle();
    await openForum(tester);
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Covoiturage du mercredi'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
}
