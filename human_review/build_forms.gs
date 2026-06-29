/**
 * build_forms.gs — Crea los Google Forms de revisión ciega a partir de form_data.json.
 *
 * USO (una sola vez):
 *  1. Sube el fichero  human_review/form_data.json  a tu Google Drive (en cualquier carpeta).
 *  2. Ve a https://script.google.com  ->  Nuevo proyecto.
 *  3. Pega TODO este fichero, guarda.
 *  4. Ejecuta  buildAll  (la primera vez te pedirá autorizar permisos de Drive/Forms/Sheets).
 *     - Si buildAll tarda demasiado (límite de 6 min), ejecuta en su lugar, uno a uno:
 *       buildSpringBoot, buildAngular, buildReact, buildDatos.
 *  5. En el registro de ejecución (Ver > Registros) tendrás las URLs de los 4 formularios
 *     y de la hoja de resultados. Comparte cada formulario con su pareja de revisores.
 *
 * Todas las respuestas de los 4 formularios caen en la MISMA Google Sheet (una pestaña por
 * formulario). El modelo va anonimizado; el harness queda visible para comparar arneses.
 */

var DATA_FILE   = 'form_data.json';
var SHEET_NAME  = 'Resultados revisión modelos IA';
var CHUNK       = 3800;   // trozo máximo de código por bloque (límite de descripción de Forms)

function buildAll()       { var d = loadData(); var ss = getSheet(); for (var fw in d.frameworks) buildForm(fw, d, ss); }
function buildSpringBoot(){ buildOne('Spring Boot'); }
function buildAngular()   { buildOne('Angular'); }
function buildReact()     { buildOne('React'); }
function buildDatos()     { buildOne('Datos'); }

function buildOne(fw) {
  var d = loadData();
  if (!d.frameworks[fw]) { throw new Error('No hay datos para el framework: ' + fw); }
  buildForm(fw, d, getSheet());
}

/** Carga form_data.json desde Drive. */
function loadData() {
  var files = DriveApp.getFilesByName(DATA_FILE);
  if (!files.hasNext()) { throw new Error('No encuentro ' + DATA_FILE + ' en tu Drive. Súbelo primero.'); }
  return JSON.parse(files.next().getBlob().getDataAsString('UTF-8'));
}

/** Crea (o reutiliza) la hoja de resultados y devuelve su id. */
function getSheet() {
  var it = DriveApp.getFilesByName(SHEET_NAME);
  if (it.hasNext()) { return SpreadsheetApp.open(it.next()).getId(); }
  var ss = SpreadsheetApp.create(SHEET_NAME);
  Logger.log('HOJA DE RESULTADOS: ' + ss.getUrl());
  return ss.getId();
}

/** Construye el formulario de un framework. */
function buildForm(fw, d, ssId) {
  var form = FormApp.create('Evaluación ciega de IA — ' + fw);
  form.setDescription(d.objetivo + '\n\n' + d.instrucciones)
      .setCollectEmail(true)        // identifica al revisor (para reconciliar luego)
      .setProgressBar(true)
      .setShowLinkToRespondAgain(false);

  // --- Cabecera: objetivo, instrucciones y rúbrica al PRINCIPIO ---
  var rub = 'RÚBRICA — puntúa cada eje de 1 (muy malo) a 5 (excelente):\n';
  for (var i = 0; i < d.rubrica.length; i++) {
    rub += '\n' + d.rubrica[i][0] + ' — ' + d.rubrica[i][1];
  }
  form.addSectionHeaderItem().setTitle('Antes de empezar').setHelpText(rub);

  // Pregunta inicial: nombre del revisor (además del email).
  form.addTextItem().setTitle('Tu nombre (para la reconciliación)').setRequired(true);

  // --- Una sección por respuesta ---
  var items = d.frameworks[fw];
  for (var n = 0; n < items.length; n++) {
    var it = items[n];
    var header = 'Respuesta ' + (n + 1) + ' / ' + items.length +
                 '  ·  ' + it.modelo + '  ·  ' + it.harness + '  ·  ' + it.tarea;
    var fairStatus = it.fair_status || '';
    var fairNotes = it.fair_notes ? ('\nNotas automáticas: ' + it.fair_notes) : '';
    var source = it.automatic_source ? ('\nFuente automática: ' + it.automatic_source) : '';
    var ctx = 'Harness: ' + it.harness + '\n' +
              'Tarea (' + it.tipo + '): ' + it.tarea_desc +
              '\nBuild automático justo: ' + (String(it.build_ok) === 'True' ? 'PASA' : 'FALLA') +
              '\nTest automático justo: ' + (String(it.test_ok) === 'True' ? 'PASA' : 'FALLA') +
              '\nFair status: ' + fairStatus + source + fairNotes;
    form.addPageBreakItem().setTitle(header).setHelpText(ctx);

    // Código troceado en bloques (cada uno como cabecera de sección, solo lectura).
    var parts = chunkText(it.codigo, CHUNK);
    for (var p = 0; p < parts.length; p++) {
      var lbl = parts.length > 1 ? ('CÓDIGO A EVALUAR (' + (p + 1) + '/' + parts.length + ')') : 'CÓDIGO A EVALUAR';
      form.addSectionHeaderItem().setTitle(lbl).setHelpText(parts[p]);
    }

    // 5 ejes (escala 1–5, obligatorios).
    for (var e = 0; e < d.rubrica.length; e++) {
      form.addScaleItem()
          .setTitle(it.modelo + ' · ' + it.harness + ' · ' + it.tarea + ' — ' + d.rubrica[e][0])
          .setBounds(1, 5)
          .setLabels('Muy malo', 'Excelente')
          .setRequired(true);
    }
    // Comentario opcional.
    form.addParagraphTextItem()
        .setTitle('Comentario (opcional) — ' + it.modelo + ' · ' + it.harness + ' · ' + it.tarea);
  }

  // Volcar respuestas a la hoja compartida (crea una pestaña por formulario).
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ssId);
  Logger.log('FORM ' + fw + ': ' + form.getPublishedUrl());
  Logger.log('  (editar): ' + form.getEditUrl());
}

/** Parte un string en trozos de tamaño maximo n. */
function chunkText(s, n) {
  var out = [];
  for (var i = 0; i < s.length; i += n) { out.push(s.substring(i, i + n)); }
  return out.length ? out : [''];
}
