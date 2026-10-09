/// School forum (EXISTING backend, ADR 0015): collective discussions of the
/// school or of a class — distinct from private messaging and complaints.
///
///   GET  /forum/spaces/                    spaces the server lets me see
///   GET  /forum/threads/?space=&page=      threads, most recent activity first
///   POST /forum/threads/ {space, title, body}
///   GET  /forum/threads/{id}/              GET/POST /forum/threads/{id}/posts/
///   DELETE /forum/posts/{id}/              my own post (moderation stays with the administration)
///
/// Who belongs to a space, who may write, what is locked: the SERVER decides
/// (guardians have no forum). The app only shows its answers.
library;

import 'communication.dart';

const threadStatuses = {'OPEN': 'Ouvert', 'LOCKED': 'Verrouillé', 'ARCHIVED': 'Archivé'};

class ForumSpace {
  ForumSpace({required this.id, required this.name, this.description, this.announcementsOnly = false});

  factory ForumSpace.fromJson(Map<String, dynamic> json) => ForumSpace(
    id: '${json['id']}',
    name: (json['name'] as String?) ?? '',
    description: json['description'] as String?,
    announcementsOnly: json['announcements_only'] == true,
  );

  final String id;
  final String name;
  final String? description;

  /// Only the administration publishes here (members read).
  final bool announcementsOnly;
}

class ForumThread {
  ForumThread({
    required this.id,
    required this.spaceId,
    required this.title,
    required this.type,
    required this.status,
    required this.authorName,
    this.statusReason,
    this.createdAt,
    this.lastPostAt,
  });

  factory ForumThread.fromJson(Map<String, dynamic> json) => ForumThread(
    id: '${json['id']}',
    spaceId: '${json['space']}',
    title: (json['title'] as String?) ?? '',
    type: (json['thread_type'] as String?) ?? 'GENERAL',
    status: (json['status'] as String?) ?? 'OPEN',
    statusReason: json['status_reason'] as String?,
    authorName: (json['author_name'] as String?) ?? '',
    createdAt: schoolTime(json['created_at']),
    lastPostAt: schoolTime(json['last_post_at']),
  );

  final String id;
  final String spaceId;
  final String title;
  final String type;
  final String status;
  final String? statusReason;
  final String authorName;
  final DateTime? createdAt;
  final DateTime? lastPostAt;

  bool get isAnnouncement => type == 'ANNOUNCEMENT';
  bool get isOpen => status == 'OPEN';

  /// Replies are possible on an open discussion (announcements are read-only;
  /// the server refuses anything else anyway).
  bool get acceptsReplies => isOpen && !isAnnouncement;
  String get statusLabel => threadStatuses[status] ?? status;
}

class ForumPost {
  ForumPost({
    required this.id,
    required this.authorId,
    required this.authorName,
    this.body,
    this.createdAt,
    this.deletedAt,
    this.isAnnouncement = false,
  });

  factory ForumPost.fromJson(Map<String, dynamic> json) => ForumPost(
    id: '${json['id']}',
    authorId: '${json['author']}',
    authorName: (json['author_name'] as String?) ?? '',
    body: json['body'] as String?,
    createdAt: schoolTime(json['created_at']),
    deletedAt: schoolTime(json['deleted_at']),
    isAnnouncement: json['post_type'] == 'ANNOUNCEMENT',
  );

  final String id;

  /// Membership id of the author (compared with mine for "delete my post").
  final String authorId;
  final String authorName;

  /// null when the post was removed (the server hides its content).
  final String? body;
  final DateTime? createdAt;
  final DateTime? deletedAt;
  final bool isAnnouncement;

  bool get deleted => deletedAt != null;
}

/// One page of a paginated forum list.
class ForumPage<T> {
  ForumPage(this.rows, {required this.hasNext, required this.page});

  final List<T> rows;
  final bool hasNext;
  final int page;
}
