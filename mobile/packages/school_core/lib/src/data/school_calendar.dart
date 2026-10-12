/// The school's calendar breaks (GET /school-breaks/, readable by every
/// member): holidays, public holidays, exams — when the gate and the
/// planning change for everyone.
library;

import '../api/api_client.dart';
import 'communication.dart';
import '../l10n/l10n.dart';

const _breakTypesFr = {'HOLIDAY': 'Vacances', 'PUBLIC_HOLIDAY': 'Jour férié', 'EXAM': 'Examens', 'OTHER': 'Autre'};

/// Labels in the CURRENT language (French source: [_breakTypesFr]).
Map<String, String> get breakTypes => trMap(_breakTypesFr);

class SchoolBreakItem {
  SchoolBreakItem({required this.name, required this.type, this.start, this.end});

  factory SchoolBreakItem.fromJson(Map<String, dynamic> json) => SchoolBreakItem(
    name: (json['name'] as String?) ?? '',
    type: (json['break_type'] as String?) ?? '',
    start: schoolTime(json['start_datetime']),
    end: schoolTime(json['end_datetime']),
  );

  final String name;
  final String type;
  final DateTime? start;
  final DateTime? end;

  String get typeLabel => breakTypes[type] ?? type;
}

/// Breaks still to come (or in progress), soonest first.
Future<List<SchoolBreakItem>> upcomingBreaks(ApiClient api, {DateTime? now}) async {
  final today = now ?? DateTime.now();
  final rows = (await api.listAll('school-breaks/')).map(SchoolBreakItem.fromJson);
  return rows.where((b) => b.end == null || !b.end!.isBefore(today)).toList()
    ..sort((a, b) => (a.start ?? today).compareTo(b.start ?? today));
}
