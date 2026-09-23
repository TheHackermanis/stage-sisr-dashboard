"""Détection des missions / technologies citées dans un texte (offre ou description)."""

import re

from app.services.referentiels import normaliser

# Libellé affiché -> motifs (sur texte normalisé : minuscules, sans accents)
TECHNOS: dict[str, list[str]] = {
    "Windows Server": [r"windows server", r"\bwsus\b", r"\bgpo\b"],
    "Active Directory": [r"active directory", r"\bad ds\b", r"\bldap\b"],
    "Linux": [r"\blinux\b", r"\bdebian\b", r"\bubuntu\b", r"\bred ?hat\b", r"\brhel\b", r"\bcentos\b"],
    "Réseau": [r"\breseaux?\b", r"\blan\b", r"\bwan\b", r"\bvlan\b", r"\btcp ip\b", r"\bswitch", r"\brouteur"],
    "Cisco": [r"\bcisco\b", r"\bccna\b"],
    "Pare-feu": [r"pare feu", r"firewall", r"fortinet", r"fortigate", r"stormshield", r"pfsense", r"palo alto"],
    "VMware": [r"vmware", r"vsphere", r"\besxi?\b"],
    "Proxmox": [r"proxmox"],
    "Hyper-V": [r"hyper v"],
    "Virtualisation": [r"virtualisation", r"virtualization"],
    "Cybersécurité": [r"cyber", r"securite informatique", r"\bsoc\b", r"\bsiem\b", r"pentest", r"\bssi\b"],
    "Support N1/N2": [r"support", r"helpdesk", r"help desk", r"service desk", r"\bn1\b", r"\bn2\b", r"assistance utilisateur"],
    "Cloud": [r"\bcloud\b", r"\bazure\b", r"\baws\b", r"\bgcp\b", r"hebergement"],
    "Microsoft 365": [r"office 365", r"microsoft 365", r"\bm365\b", r"\bo365\b", r"exchange", r"intune"],
    "Sauvegarde": [r"sauvegarde", r"backup", r"veeam"],
    "Supervision": [r"supervision", r"zabbix", r"nagios", r"centreon", r"grafana", r"prtg"],
    "Scripting": [r"powershell", r"\bbash\b", r"\bansible\b", r"\bpython\b"],
    "Téléphonie / ToIP": [r"\btoip\b", r"\bvoip\b", r"telephonie", r"\bipbx\b"],
    "Infogérance": [r"infogerance", r"maintenance informatique", r"gestion d installations informatiques",
                    r"tierce maintenance"],
    "Télécoms / Fibre": [r"telecommunication", r"\bfibre\b", r"\bftth\b"],
    "Docker / conteneurs": [r"docker", r"kubernetes", r"\bk8s\b"],
    "GLPI / ITSM": [r"\bglpi\b", r"\bitsm\b", r"\bitil\b"],
}

_COMPILED = {label: [re.compile(p) for p in pats] for label, pats in TECHNOS.items()}


def detecter_technos(texte: str | None) -> list[str]:
    t = normaliser(texte)
    if not t:
        return []
    return [label for label, pats in _COMPILED.items() if any(p.search(t) for p in pats)]
