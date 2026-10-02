"""People of a school. Split in modules for readability; Django sees one app."""

from .guardians import GuardianProfile, GuardianStatus
from .parents import Language, ParentProfile, ParentStudent, RelationshipType, VerificationMethod
from .staff import (
    CompatibilityOverride,
    CompatibilityResult,
    EmployeeProfile,
    EmployeeType,
    EmploymentStatus,
    ProfessionalStatus,
    QualificationSource,
    QualificationStatus,
    StaffFunction,
    StaffFunctionAssignment,
    StaffProfile,
    TeacherProfile,
    TeacherSubjectQualification,
)
from .students import (
    EnrollmentStatus,
    HardDeleteForbidden,
    PromotionStatus,
    Sex,
    Student,
    StudentEnrollment,
    StudentStatus,
)

__all__ = [
    "CompatibilityOverride",
    "CompatibilityResult",
    "EmployeeProfile",
    "EmployeeType",
    "EmploymentStatus",
    "EnrollmentStatus",
    "GuardianProfile",
    "GuardianStatus",
    "HardDeleteForbidden",
    "Language",
    "ParentProfile",
    "ParentStudent",
    "ProfessionalStatus",
    "PromotionStatus",
    "QualificationSource",
    "QualificationStatus",
    "RelationshipType",
    "Sex",
    "StaffFunction",
    "StaffFunctionAssignment",
    "StaffProfile",
    "Student",
    "StudentEnrollment",
    "StudentStatus",
    "TeacherProfile",
    "TeacherSubjectQualification",
    "VerificationMethod",
]
