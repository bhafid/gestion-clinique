# Graph Report - gestion-clinique  (2026-11-12)

## Corpus Check
- Large corpus: 3512 files · ~2,826,736 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 1071 nodes · 2661 edges · 57 communities (32 shown, 25 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 469 edges (avg confidence: 0.95)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39

## God Nodes (most connected - your core abstractions)
1. `Patient` - 73 edges
2. `UserRole` - 57 edges
3. `AuditableModel` - 44 edges
4. `CustomUser` - 42 edges
5. `ProduitPharmaceutique` - 38 edges
6. `CoreModuleTestCase` - 36 edges
7. `Command` - 33 edges
8. `Hospitalization` - 32 edges
9. `SecurityAuditLog` - 31 edges
10. `SurgicalIntervention` - 28 edges

## Surprising Connections (you probably didn't know these)
- `SafetyChecklistOMSInline` --uses--> `SafetyChecklistOMS`  [INFERRED]
  apps/chirurgie/admin.py → apps/chirurgie/models.py
- `OperativeReportInline` --uses--> `OperativeReport`  [INFERRED]
  apps/chirurgie/admin.py → apps/chirurgie/models.py
- `LigneCommandeAchatInline` --uses--> `LigneCommandeAchat`  [INFERRED]
  apps/pharmacie/admin.py → apps/pharmacie/models.py
- `SurgicalInterventionForm` --uses--> `SurgicalIntervention`  [INFERRED]
  apps/chirurgie/forms.py → apps/chirurgie/models.py
- `SafetyChecklistOMSForm` --uses--> `SafetyChecklistOMS`  [INFERRED]
  apps/chirurgie/forms.py → apps/chirurgie/models.py

## Import Cycles
- None detected.

## Communities (57 total, 25 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.06
Nodes (32): SpecializedInterventionReportAdmin, UrodynamicAssessmentAdmin, UrologicalHistoryAdmin, SpecializedInterventionReportForm, Meta, UrodynamicAssessmentForm, Meta, UrologicalHistoryForm (+24 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (17): AuditActionType, PatientStatusColor, SecurityAuditLog, Meta, admission_consent_pdf_view(), api_patient_status_history_view(), api_status_configs_view(), ClinicSettingsView (+9 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (21): Command, AppointmentStatus, BedStatus, BloodGroup, CustomUser, Meta, Department, Meta (+13 more)

### Community 3 - "Community 3"
Cohesion: 0.06
Nodes (23): AnthropometricRecordAdmin, VaccinationRecordAdmin, AnthropometricRecordForm, Meta, VaccinationRecordForm, Meta, AnthropometricRecord, Meta (+15 more)

### Community 4 - "Community 4"
Cohesion: 0.10
Nodes (21): BaseCalculRemboursementChoices, LettreCleNGAPChoices, ModePaiementAlgerieChoices, StatutBordereauChoices, StatutFactureChoices, TypeActeFacturableChoices, TypeOrganismePayeurChoices, ajouter_acte_ngap_a_facture() (+13 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (16): Migration, Migration, RoleInactivityTimeoutMiddleware, StrictAuthenticationMiddleware, Migration, Migration, Migration, Migration (+8 more)

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (15): AppointmentForm, Meta, DutyShiftForm, Meta, HospitalizationForm, Meta, PatientForm, Meta (+7 more)

### Community 7 - "Community 7"
Cohesion: 0.08
Nodes (13): AjouterActeNGAPFactureView, AjouterMedicamentPPAFactureView, api_simuler_droit_timbre(), CreerConventionPatientView, CreerFacturePatientView, EnregistrerPaiementFactureView, FactureOfficielleAlgeriePrintView, GenererBordereauTiersPayantView (+5 more)

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (17): CategorieProduitChoices, CommandeAchat, Meta, MethodeRotationChoices, MouvementStock, Meta, StatutCommandeChoices, StatutLotChoices (+9 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (11): build_csv_bytes(), build_xlsx_bytes(), _col_index_to_letters(), _col_letters_to_index(), first_non_empty(), generate_valid_nir_for_patient(), normalize_col_key(), _parse_csv_raw_bytes() (+3 more)

### Community 10 - "Community 10"
Cohesion: 0.08
Nodes (6): BedAdmin, PatientAdmin, Bed, Meta, Patient, Meta

### Community 11 - "Community 11"
Cohesion: 0.08
Nodes (16): AuditableModel, Meta, ActeMedicalNGAP, Meta, BordereauTiersPayant, Meta, ConventionPriseEnCharge, Meta (+8 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (10): DeliveryRegistryAdmin, GynecologicalHistoryAdmin, PregnancyTrackingAdmin, RoutineConsultationAdmin, DeliveryRegistry, Meta, GynecologicalHistory, Meta (+2 more)

### Community 13 - "Community 13"
Cohesion: 0.09
Nodes (11): AppointmentAdmin, CustomUserAdmin, DepartmentAdmin, DutyShiftAdmin, PatientStatusConfigAdmin, PatientStatusHistoryAdmin, PatientStatusHistoryInline, PatientStatusConfig (+3 more)

### Community 14 - "Community 14"
Cohesion: 0.13
Nodes (7): AjustementInventaireTournantView, CreerCommandeDepuisSuggestionsView, DispensationFEFOView, ExportMedicamentsExcelView, ImportMedicamentsExcelView, QuarantaineRappelLotView, ReceptionLivraisonCommandeView

### Community 15 - "Community 15"
Cohesion: 0.11
Nodes (15): ActeMedicalNGAPAdmin, BordereauTiersPayantAdmin, ConventionPriseEnChargeAdmin, EtablissementFiscalAdmin, FacturePatientAdmin, LigneFactureActeInline, LigneFacturePharmacieInline, OrganismeTiersPayantAdmin (+7 more)

### Community 17 - "Community 17"
Cohesion: 0.09
Nodes (7): ChirurgieConfig, CoreConfig, FacturationConfig, GynecologieMaterniteConfig, PediatrieConfig, PharmacieConfig, UrologieConfig

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (8): ChecklistDetailView, InterventionDeleteView, InterventionDetailView, InterventionListView, InterventionUpdateView, ReportDetailView, RoleRequiredMixin, user_has_chirurgien_or_medecin()

### Community 19 - "Community 19"
Cohesion: 0.15
Nodes (10): OperatingRoomAdmin, OperativeReportAdmin, OperativeReportInline, SafetyChecklistOMSAdmin, SafetyChecklistOMSInline, SurgicalInterventionAdmin, InterventionStatus, SurgicalIntervention (+2 more)

### Community 20 - "Community 20"
Cohesion: 0.14
Nodes (3): ProduitPharmaceutiqueAdmin, ProduitPharmaceutique, Meta

### Community 21 - "Community 21"
Cohesion: 0.13
Nodes (8): CommandeAchatAdmin, FournisseurAdmin, LigneCommandeAchatInline, LotStockAdmin, LotStockInline, MouvementStockAdmin, LotStock, Meta

### Community 22 - "Community 22"
Cohesion: 0.15
Nodes (3): HospitalizationAdmin, Hospitalization, Meta

### Community 24 - "Community 24"
Cohesion: 0.13
Nodes (5): OperatingRoom, Meta, SafetyChecklistOMS, Meta, ChirurgieModuleTestCase

### Community 26 - "Community 26"
Cohesion: 0.15
Nodes (4): ShiftReplacementAdmin, ShiftReplacement, Meta, WeeklyDashboardView

### Community 28 - "Community 28"
Cohesion: 0.21
Nodes (3): clinic_branding(), get_clinic_logo_data_uri(), get_clinic_parameters_dict()

### Community 29 - "Community 29"
Cohesion: 0.23
Nodes (3): _format_date_fr(), generate_admission_consent_pdf(), normalize_admission_data()

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (3): LigneCommandeAchat, Meta, api_scan_code_barres()

### Community 31 - "Community 31"
Cohesion: 0.20
Nodes (8): OperativeReportForm, Meta, SafetyChecklistOMSForm, Meta, SurgicalInterventionForm, Meta, OperativeReport, Meta

### Community 32 - "Community 32"
Cohesion: 0.18
Nodes (3): ChecklistCreateView, InterventionCreateView, ReportCreateView

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (7): _generate_with_native_pdf(), current_ops(), draw_rect(), draw_text(), new_page(), write_section_box(), _pdf_escape()

### Community 34 - "Community 34"
Cohesion: 0.22
Nodes (3): Fournisseur, Meta, PharmacieDashboardView

### Community 37 - "Community 37"
Cohesion: 0.47
Nodes (5): _generate_with_reportlab(), _draw_footer(), __init__(), save(), showPage()

## Knowledge Gaps
- **25 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Patient` connect `Community 10` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 6`, `Community 7`, `Community 8`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 19`, `Community 23`, `Community 24`, `Community 26`, `Community 27`, `Community 34`, `Community 35`?**
  _High betweenness centrality (0.148) - this node is a cross-community bridge._
- **Are the 36 inferred relationships involving `Patient` (e.g. with `SurgicalIntervention` and `ChirurgieModuleTestCase`) actually correct?**
  _`Patient` has 36 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.055900621118012424 - nodes in this community are weakly interconnected._
- **Why does `UserRole` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 16`, `Community 18`, `Community 19`, `Community 22`, `Community 23`, `Community 24`, `Community 26`, `Community 27`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Are the 34 inferred relationships involving `UserRole` (e.g. with `SurgicalIntervention` and `ChirurgieModuleTestCase`) actually correct?**
  _`UserRole` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 1` be split into smaller, more focused modules?**
  _Cohesion score 0.07459207459207459 - nodes in this community are weakly interconnected._
- **Why does `AuditableModel` connect `Community 11` to `Community 0`, `Community 2`, `Community 3`, `Community 6`, `Community 8`, `Community 10`, `Community 12`, `Community 13`, `Community 15`, `Community 19`, `Community 20`, `Community 21`, `Community 22`, `Community 24`, `Community 26`, `Community 30`, `Community 31`, `Community 34`, `Community 35`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._