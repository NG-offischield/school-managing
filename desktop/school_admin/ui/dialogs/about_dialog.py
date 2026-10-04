"""« À propos de School Managing »: the SOFTWARE's identity (logo, name,
version). The school's own branding is not shown here: it belongs to the
official documents produced by the server."""

from PySide6.QtWidgets import QLabel

from ... import __version__
from ..branding import SOFTWARE_NAME, brand_mark
from ..widgets import FormDialog


class AboutDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__(f"À propos de {SOFTWARE_NAME}", "", parent, save_text="Fermer", width=480)
        self.cancel_button.hide()
        self.brand = brand_mark("horizontal", 56, object_name="softwareBrandLogin")
        self.body.addWidget(self.brand)
        for text, name in (
            (f"Version {__version__}", "fieldValue"),
            ("Poste d'administration de l'école : années, classes, élèves, enseignants, cours, planning.", "help"),
            (
                "Les documents officiels (bulletins, cartes, reçus, fiches de paie, emplois du temps…) portent "
                "toujours le logo et les couleurs de l'établissement, jamais celui du logiciel.",
                "help",
            ),
        ):
            label = QLabel(text, objectName=name)
            label.setWordWrap(True)
            self.body.addWidget(label)
        self.finish(required_note=False)
