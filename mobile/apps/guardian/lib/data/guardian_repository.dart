/// What the guardian app reads, through the EXISTING API only; the server
/// decides what a guardian may see:
///
///   gate (school_core GateRepository): POST /qr/scans/, GET /guardians/scans/ (MY scans only)
///   GET /school-breaks/     closures that change the gate
///   communication (school_core CommunicationRepository)
///
/// A guardian has no access to pupils' records, grades or finances: the
/// only financial hint is the solvency the server adds to a scan answer
/// (UP_TO_DATE / OVERDUE, never an amount — ADR 0013 / 0014).
library;

import 'package:school_core/school_core.dart';

class GuardianRepository extends CommunicationRepository {
  GuardianRepository(super.api) : gate = GateRepository(api);

  final GateRepository gate;

  Future<List<SchoolBreakItem>> breaks() => upcomingBreaks(api);
}
