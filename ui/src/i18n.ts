// Panel chrome strings. Language follows the OS/browser unless chosen in Settings; English is the fallback
// for any missing key. Feature names/help come from the engine (English). Add a language = add one object.
const EN = {
  media: "Media file(s)", mediaHint: "one path per line; several = batch", search: "Search features…  (Ctrl+Enter applies)",
  noMatch: "No features match.", reset: "Reset", analyze: "Analyze", plan: "Plan", apply: "Apply", applySelected: "Apply {n} selected",
  download: "Download", requires: "Requires {tier}", history: "History", settings: "Settings", whatsNew: "What's new", help: "Help (F1)",
  preset: "Preset…", saveAs: "Save current as…", save: "Save", graphics: "Graphics & MOGRTs", searchTemplates: "Search templates…",
  allTemplates: "All templates", captionPreview: "Live preview", safeZones: "Safe zones", language: "Language", share: "Share presets",
  exportPresets: "Export my presets", importPresets: "Import presets", startEngine: "Start engine", retry: "Retry",
};
type Key = keyof typeof EN;
const T: Record<string, Partial<Record<Key, string>>> = {
  en: EN,
  es: { media: "Archivo(s) de medios", search: "Buscar funciones…  (Ctrl+Enter aplica)", noMatch: "Ninguna función coincide.", reset: "Restablecer",
    analyze: "Analizar", plan: "Planificar", apply: "Aplicar", applySelected: "Aplicar {n} seleccionados", download: "Descargar", history: "Historial",
    settings: "Ajustes", whatsNew: "Novedades", help: "Ayuda (F1)", preset: "Preajuste…", saveAs: "Guardar como…", save: "Guardar",
    graphics: "Gráficos y MOGRT", searchTemplates: "Buscar plantillas…", allTemplates: "Todas las plantillas", captionPreview: "Vista previa",
    safeZones: "Zonas seguras", language: "Idioma", share: "Compartir preajustes", exportPresets: "Exportar mis preajustes", importPresets: "Importar preajustes",
    startEngine: "Iniciar motor", retry: "Reintentar" },
  fr: { media: "Fichier(s) média", search: "Rechercher…  (Ctrl+Entrée applique)", noMatch: "Aucune fonction trouvée.", reset: "Réinitialiser",
    analyze: "Analyser", plan: "Planifier", apply: "Appliquer", applySelected: "Appliquer {n} sélectionnés", download: "Télécharger", history: "Historique",
    settings: "Paramètres", whatsNew: "Nouveautés", help: "Aide (F1)", preset: "Préréglage…", saveAs: "Enregistrer sous…", save: "Enregistrer",
    graphics: "Graphiques et MOGRT", searchTemplates: "Rechercher des modèles…", allTemplates: "Tous les modèles", captionPreview: "Aperçu en direct",
    safeZones: "Zones de sécurité", language: "Langue", share: "Partager les préréglages", exportPresets: "Exporter mes préréglages",
    importPresets: "Importer des préréglages", startEngine: "Démarrer le moteur", retry: "Réessayer" },
  de: { media: "Mediendatei(en)", search: "Funktionen suchen…  (Strg+Enter anwenden)", noMatch: "Keine Treffer.", reset: "Zurücksetzen",
    analyze: "Analysieren", plan: "Planen", apply: "Anwenden", applySelected: "{n} ausgewählte anwenden", download: "Herunterladen", history: "Verlauf",
    settings: "Einstellungen", whatsNew: "Neuigkeiten", help: "Hilfe (F1)", preset: "Vorgabe…", saveAs: "Speichern als…", save: "Speichern",
    graphics: "Grafiken & MOGRTs", searchTemplates: "Vorlagen suchen…", allTemplates: "Alle Vorlagen", captionPreview: "Live-Vorschau",
    safeZones: "Sichere Bereiche", language: "Sprache", share: "Vorgaben teilen", exportPresets: "Meine Vorgaben exportieren",
    importPresets: "Vorgaben importieren", startEngine: "Engine starten", retry: "Erneut versuchen" },
  pt: { media: "Arquivo(s) de mídia", search: "Buscar recursos…  (Ctrl+Enter aplica)", noMatch: "Nenhum recurso encontrado.", reset: "Redefinir",
    analyze: "Analisar", plan: "Planejar", apply: "Aplicar", applySelected: "Aplicar {n} selecionados", download: "Baixar", history: "Histórico",
    settings: "Configurações", whatsNew: "Novidades", help: "Ajuda (F1)", preset: "Predefinição…", saveAs: "Salvar como…", save: "Salvar",
    graphics: "Gráficos e MOGRTs", searchTemplates: "Buscar modelos…", allTemplates: "Todos os modelos", captionPreview: "Prévia ao vivo",
    safeZones: "Zonas seguras", language: "Idioma", share: "Compartilhar predefinições", exportPresets: "Exportar minhas predefinições",
    importPresets: "Importar predefinições", startEngine: "Iniciar motor", retry: "Tentar de novo" },
  it: { media: "File multimediali", search: "Cerca funzioni…  (Ctrl+Invio applica)", noMatch: "Nessuna funzione trovata.", reset: "Ripristina",
    analyze: "Analizza", plan: "Pianifica", apply: "Applica", applySelected: "Applica {n} selezionati", download: "Scarica", history: "Cronologia",
    settings: "Impostazioni", whatsNew: "Novità", help: "Aiuto (F1)", preset: "Preset…", saveAs: "Salva come…", save: "Salva",
    graphics: "Grafiche e MOGRT", searchTemplates: "Cerca modelli…", allTemplates: "Tutti i modelli", captionPreview: "Anteprima dal vivo",
    safeZones: "Aree sicure", language: "Lingua", share: "Condividi preset", exportPresets: "Esporta i miei preset", importPresets: "Importa preset",
    startEngine: "Avvia motore", retry: "Riprova" },
  tr: { media: "Medya dosyaları", search: "Özellik ara…  (Ctrl+Enter uygular)", noMatch: "Eşleşen özellik yok.", reset: "Sıfırla",
    analyze: "Analiz et", plan: "Planla", apply: "Uygula", applySelected: "Seçili {n} öğeyi uygula", download: "İndir", history: "Geçmiş",
    settings: "Ayarlar", whatsNew: "Yenilikler", help: "Yardım (F1)", preset: "Ön ayar…", saveAs: "Farklı kaydet…", save: "Kaydet",
    graphics: "Grafikler ve MOGRT", searchTemplates: "Şablon ara…", allTemplates: "Tüm şablonlar", captionPreview: "Canlı önizleme",
    safeZones: "Güvenli alanlar", language: "Dil", share: "Ön ayarları paylaş", exportPresets: "Ön ayarlarımı dışa aktar",
    importPresets: "Ön ayarları içe aktar", startEngine: "Motoru başlat", retry: "Tekrar dene" },
  pl: { media: "Pliki multimedialne", search: "Szukaj funkcji…  (Ctrl+Enter stosuje)", noMatch: "Brak pasujących funkcji.", reset: "Resetuj",
    analyze: "Analizuj", plan: "Zaplanuj", apply: "Zastosuj", applySelected: "Zastosuj {n} zaznaczonych", download: "Pobierz", history: "Historia",
    settings: "Ustawienia", whatsNew: "Co nowego", help: "Pomoc (F1)", preset: "Ustawienie…", saveAs: "Zapisz jako…", save: "Zapisz",
    graphics: "Grafiki i MOGRT", searchTemplates: "Szukaj szablonów…", allTemplates: "Wszystkie szablony", captionPreview: "Podgląd na żywo",
    safeZones: "Strefy bezpieczne", language: "Język", share: "Udostępnij ustawienia", exportPresets: "Eksportuj moje ustawienia",
    importPresets: "Importuj ustawienia", startEngine: "Uruchom silnik", retry: "Ponów" },
  hi: { media: "मीडिया फ़ाइलें", search: "फ़ीचर खोजें…  (Ctrl+Enter लागू करे)", noMatch: "कोई फ़ीचर नहीं मिला।", reset: "रीसेट",
    analyze: "विश्लेषण", plan: "योजना", apply: "लागू करें", applySelected: "{n} चुने हुए लागू करें", download: "डाउनलोड", history: "इतिहास",
    settings: "सेटिंग्स", whatsNew: "नया क्या है", help: "सहायता (F1)", preset: "प्रीसेट…", saveAs: "इस नाम से सहेजें…", save: "सहेजें",
    graphics: "ग्राफ़िक्स और MOGRT", searchTemplates: "टेम्पलेट खोजें…", allTemplates: "सभी टेम्पलेट", captionPreview: "लाइव प्रीव्यू",
    safeZones: "सुरक्षित क्षेत्र", language: "भाषा", share: "प्रीसेट साझा करें", exportPresets: "मेरे प्रीसेट निर्यात करें",
    importPresets: "प्रीसेट आयात करें", startEngine: "इंजन शुरू करें", retry: "फिर कोशिश करें" },
  ar: { media: "ملفات الوسائط", search: "ابحث عن الميزات…  (Ctrl+Enter للتطبيق)", noMatch: "لا توجد ميزات مطابقة.", reset: "إعادة تعيين",
    analyze: "تحليل", plan: "خطة", apply: "تطبيق", applySelected: "تطبيق {n} محدد", download: "تنزيل", history: "السجل",
    settings: "الإعدادات", whatsNew: "الجديد", help: "مساعدة (F1)", preset: "إعداد مسبق…", saveAs: "حفظ باسم…", save: "حفظ",
    graphics: "الرسومات وقوالب MOGRT", searchTemplates: "ابحث في القوالب…", allTemplates: "كل القوالب", captionPreview: "معاينة مباشرة",
    safeZones: "المناطق الآمنة", language: "اللغة", share: "مشاركة الإعدادات", exportPresets: "تصدير إعداداتي", importPresets: "استيراد إعدادات",
    startEngine: "تشغيل المحرك", retry: "إعادة المحاولة" },
};
export const LANGS: Record<string, string> = { auto: "Auto (system)", en: "English", es: "Español", fr: "Français", de: "Deutsch", pt: "Português",
  it: "Italiano", tr: "Türkçe", pl: "Polski", hi: "हिन्दी", ar: "العربية" };
const RTL = new Set(["ar", "he", "fa", "ur"]);
let lang = "en";

export function setLang(choice: string) {
  const sys = (typeof navigator !== "undefined" && navigator.language) || "en";
  lang = (choice === "auto" ? sys : choice).slice(0, 2).toLowerCase();
  if (!T[lang]) lang = "en";
  document.documentElement.lang = lang;
  document.documentElement.dir = RTL.has(lang) ? "rtl" : "ltr";
}

export function t(k: Key, vars: Record<string, string | number> = {}) {
  return (T[lang]?.[k] ?? EN[k]).replace(/\{(\w+)\}/g, (_, v) => String(vars[v] ?? ""));
}
