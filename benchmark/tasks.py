"""Canonical benchmark task registry."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkTask:
    name: str
    stack: str
    baseline: str
    target_file: str
    prompt: str
    build_cmd: list[str]
    test_cmd: list[str] | None
    seed_patches: dict[str, tuple[str, str]] = field(default_factory=dict)
    new_files: dict[str, str] = field(default_factory=dict)
    copy_ignore: tuple[str, ...] = ()
    link_node_modules: bool = False
    test_ok_equals_build: bool = False
    baseline_commit: str | None = None


BUG1_TEST = """\
import reducer from './articleList';
import { ARTICLE_FAVORITED } from '../constants/actionTypes';

test('ARTICLE_FAVORITED debe actualizar favoritesCount', () => {
  const state = {
    articles: [{ slug: 'test-slug', favorited: false, favoritesCount: 5 }]
  };
  const action = {
    type: ARTICLE_FAVORITED,
    payload: { article: { slug: 'test-slug', favorited: true, favoritesCount: 6 } }
  };
  const result = reducer(state, action);
  expect(result.articles[0].favorited).toBe(true);
  expect(result.articles[0].favoritesCount).toBe(6);
});
"""

FEAT1_STUB = """\
/**
 * Calcula el tiempo de lectura estimado en minutos.
 * @param {string} body - Texto del artículo
 * @returns {number} Minutos de lectura (mínimo 1)
 */
export default function getReadingTime(body) {
  // TODO: implementar
  return 0;
}
"""

FEAT1_TEST = """\
import getReadingTime from './readingTime';

test('devuelve 1 para texto vacío o muy corto', () => {
  expect(getReadingTime('')).toBe(1);
  expect(getReadingTime('hola')).toBe(1);
});

test('devuelve 1 para exactamente 200 palabras', () => {
  const body = Array(200).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(1);
});

test('devuelve 2 para 400 palabras', () => {
  const body = Array(400).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(2);
});

test('devuelve 3 para 600 palabras', () => {
  const body = Array(600).fill('palabra').join(' ');
  expect(getReadingTime(body)).toBe(3);
});
"""

FEAT2_TEST = """\
import reducer from './articleList';

test('FILTER_BY_AUTHOR filtra artículos por username del autor', () => {
  const state = {
    articles: [
      { slug: 'a', author: { username: 'alice' }, title: 'A', favorited: false, favoritesCount: 0 },
      { slug: 'b', author: { username: 'bob' },   title: 'B', favorited: false, favoritesCount: 0 },
      { slug: 'c', author: { username: 'alice' }, title: 'C', favorited: false, favoritesCount: 0 }
    ]
  };
  const action = { type: 'FILTER_BY_AUTHOR', author: 'alice' };
  const result = reducer(state, action);
  expect(result.articles).toHaveLength(2);
  expect(result.articles.every(a => a.author.username === 'alice')).toBe(true);
  expect(result.filteredByAuthor).toBe('alice');
});
"""

TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        name="bug1-petvalidator",
        stack="springboot",
        baseline="baselines/petclinic",
        target_file="src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java",
        prompt=(
            "Reporte de bug: al validar una mascota, un nombre formado solo por "
            "espacios en blanco (espacios, tabuladores, saltos de linea) se acepta "
            "como valido, cuando deberia rechazarse como obligatorio/vacio. "
            "Corrige la validacion en este fichero, respetando el estilo del proyecto. "
            "Devuelve SOLO el contenido completo y corregido del fichero, en un unico "
            "bloque de codigo."
        ),
        build_cmd=["mvn", "-q", "-DskipTests", "compile"],
        test_cmd=["mvn", "-q", "-Dtest=PetControllerTests", "test"],
        copy_ignore=("target", ".git"),
    ),
    BenchmarkTask(
        name="bug2-ownercontroller",
        stack="springboot",
        baseline="baselines/petclinic",
        target_file="src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java",
        prompt=(
            "Reporte de bug: en la busqueda de propietarios, cuando hay varios "
            "resultados la aplicacion redirige directamente al detalle de un "
            "propietario en lugar de mostrar la lista paginada. Correcto: un unico "
            "resultado va al detalle; varios resultados muestran la lista. Corrigelo "
            "en este fichero, respetando el estilo del proyecto. Devuelve SOLO el "
            "contenido completo y corregido del fichero, en un unico bloque de codigo."
        ),
        build_cmd=["mvn", "-q", "-DskipTests", "compile"],
        test_cmd=["mvn", "-q", "-Dtest=OwnerControllerTests", "test"],
        copy_ignore=("target", ".git"),
    ),
    BenchmarkTask(
        name="sb-feat1-name-length",
        stack="springboot",
        baseline="baselines/petclinic-feat1",
        target_file="src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java",
        prompt=(
            "Feature request: add validation to PetValidator so that a pet name longer than "
            "50 characters is rejected with error code 'tooLong'. "
            "The following test must pass:\n\n"
            "  void processCreationFormWithTooLongName() {\n"
            "      mockMvc.perform(post(...).param(\"name\", \"A\".repeat(51))\n"
            "          .param(\"type\", \"hamster\").param(\"birthDate\", \"2015-02-12\"))\n"
            "      .andExpect(model().attributeHasFieldErrorCode(\"pet\", \"name\", \"tooLong\"))\n"
            "  }\n\n"
            "Modify ONLY the validate() method in PetValidator. Respect the existing code style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["mvn", "-q", "-DskipTests", "compile"],
        test_cmd=["mvn", "-q", "-Dtest=PetControllerTests#processCreationFormWithTooLongName", "test"],
        copy_ignore=("target", ".git"),
    ),
    BenchmarkTask(
        name="ng-bug1-missing-input",
        stack="angular",
        baseline="baselines/angular-conduit",
        target_file="src/app/features/article/components/article-list.component.ts",
        prompt=(
            "Bug report: the Angular build fails with a template binding error. "
            "The @Input() decorator was accidentally removed from the 'config' property "
            "in ArticleListComponent, so Angular's strict template checking rejects "
            "the [config]=\"...\" binding in the parent template.\n\n"
            "Fix the component by restoring the missing @Input() decorator on the 'config' property. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=None,
        seed_patches={
            "src/app/features/article/components/article-list.component.ts": (
                "  @Input() limit!: number;\n  @Input() config!: ArticleListConfig;",
                "  @Input() limit!: number;\n  config!: ArticleListConfig;",
            )
        },
        copy_ignore=("node_modules", ".git", "dist", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
        test_ok_equals_build=True,
    ),
    BenchmarkTask(
        name="ng-feat1-reading-time",
        stack="angular",
        baseline="baselines/angular-conduit",
        target_file="src/app/features/article/components/article-preview.component.ts",
        prompt=(
            "Feature request: add a reading time estimate to the article preview. "
            "The template already calls getReadingTime(article().body) but the method "
            "does not exist in the component class, causing a TypeScript build error.\n\n"
            "Implement getReadingTime(body: string): number in the component class:\n"
            "- Count words by splitting on whitespace\n"
            "- Divide by 200 (average reading speed wpm)\n"
            "- Return minimum 1\n\n"
            "Follow Angular 21 best practices (signals, ChangeDetectionStrategy.OnPush). "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=None,
        seed_patches={
            "src/app/features/article/components/article-preview.component.ts": (
                "        <span>Read more...</span>",
                "        <span>Read more...</span>\n"
                "        <span class=\"reading-time\">{{ getReadingTime(article().body) }} min read</span>",
            )
        },
        copy_ignore=("node_modules", ".git", "dist", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
        test_ok_equals_build=True,
    ),
    BenchmarkTask(
        name="ng-feat2-service-search",
        stack="angular",
        baseline="baselines/angular-conduit",
        target_file="src/app/features/article/services/articles.service.ts",
        prompt=(
            "Feature request: implement the search() method in ArticlesService. "
            "The service now declares it implements ArticlesRepository, but the search() "
            "method is missing, causing a TypeScript compilation error.\n\n"
            "Implement search(query: string): Observable<Article[]> that:\n"
            "- Calls GET /articles with query param 'q' set to the query string\n"
            "- Returns the articles array from the response\n"
            "- Uses the same HttpClient patterns already used in the service\n\n"
            "Follow Angular 21 and RxJS best practices. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=None,
        seed_patches={
            "src/app/features/article/services/articles.service.ts": (
                "@Injectable({ providedIn: 'root' })\nexport class ArticlesService {",
                "interface ArticlesRepository {\n"
                "  query(config: ArticleListConfig): Observable<{ articles: Article[]; articlesCount: number }>;\n"
                "  get(slug: string): Observable<Article>;\n"
                "  delete(slug: string): Observable<void>;\n"
                "  create(article: Partial<Article>): Observable<Article>;\n"
                "  update(article: Partial<Article>): Observable<Article>;\n"
                "  favorite(slug: string): Observable<Article>;\n"
                "  unfavorite(slug: string): Observable<void>;\n"
                "  search(query: string): Observable<Article[]>;\n"
                "}\n\n"
                "@Injectable({ providedIn: 'root' })\n"
                "export class ArticlesService implements ArticlesRepository {",
            )
        },
        copy_ignore=("node_modules", ".git", "dist", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
        test_ok_equals_build=True,
    ),
    BenchmarkTask(
        name="re-bug1-favorite-count",
        stack="react",
        baseline="baselines/react-conduit",
        target_file="src/reducers/articleList.js",
        prompt=(
            "Bug report: in the Redux reducer, the ARTICLE_FAVORITED action updates "
            "the 'favorited' flag but does NOT update 'favoritesCount'. "
            "As a result, the favorite counter displayed in the UI never changes.\n\n"
            "The following test must pass:\n"
            "  expect(result.articles[0].favoritesCount).toBe(6)  // was 5, favorited → true\n\n"
            "Fix the reducer so that both 'favorited' and 'favoritesCount' are updated "
            "from action.payload.article. Respect the existing code style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=["npm", "test", "--", "--watchAll=false", "--testPathPattern=articleList.test"],
        seed_patches={
            "src/reducers/articleList.js": (
                "              favorited: action.payload.article.favorited,\n"
                "              favoritesCount: action.payload.article.favoritesCount",
                "              favorited: action.payload.article.favorited",
            )
        },
        new_files={"src/reducers/articleList.test.js": BUG1_TEST},
        copy_ignore=("node_modules", ".git", "build", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
    ),
    BenchmarkTask(
        name="re-feat1-reading-time",
        stack="react",
        baseline="baselines/react-conduit",
        target_file="src/utils/readingTime.js",
        prompt=(
            "Feature request: implement the getReadingTime(body) function so all tests pass.\n\n"
            "Requirements:\n"
            "- Count words by splitting the body string on whitespace\n"
            "- Divide word count by 200 (average reading speed in wpm)\n"
            "- Use Math.ceil and return minimum 1\n"
            "- Handle empty string or null body (return 1)\n\n"
            "The function is exported as default. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=["npm", "test", "--", "--watchAll=false", "--testPathPattern=readingTime.test"],
        new_files={
            "src/utils/readingTime.js": FEAT1_STUB,
            "src/utils/readingTime.test.js": FEAT1_TEST,
        },
        copy_ignore=("node_modules", ".git", "build", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
    ),
    BenchmarkTask(
        name="re-feat2-author-filter",
        stack="react",
        baseline="baselines/react-conduit",
        target_file="src/reducers/articleList.js",
        prompt=(
            "Feature request: add a FILTER_BY_AUTHOR case to the articleList reducer.\n\n"
            "The new action has shape: { type: 'FILTER_BY_AUTHOR', author: string }\n\n"
            "The reducer must:\n"
            "- Filter state.articles to only those where article.author.username === action.author\n"
            "- Set state.filteredByAuthor = action.author\n"
            "- Keep all other state fields unchanged\n\n"
            "The following test must pass:\n"
            "  const result = reducer(state, { type: 'FILTER_BY_AUTHOR', author: 'alice' });\n"
            "  expect(result.articles).toHaveLength(2);\n"
            "  expect(result.filteredByAuthor).toBe('alice');\n\n"
            "Respect the existing Redux reducer style. "
            "Return ONLY the complete corrected file content in a single code block."
        ),
        build_cmd=["npm", "run", "build"],
        test_cmd=["npm", "test", "--", "--watchAll=false", "--testPathPattern=articleListFilter.test"],
        new_files={"src/reducers/articleListFilter.test.js": FEAT2_TEST},
        copy_ignore=("node_modules", ".git", "build", "*.pack", "*.idx", "*.rev"),
        link_node_modules=True,
    ),
    BenchmarkTask(
        name="data-bug1-sales-genre",
        stack="data",
        baseline="baselines/data-chinook",
        target_file="bug1_sales_genre.py",
        prompt=(
            "Bug report: the following Python/pandas script is supposed to return the top 5 "
            "music genres by number of units sold (sum of InvoiceLine.Quantity), but it "
            "produces wrong counts due to an incorrect JOIN condition.\n\n"
            "Schema (relevant tables):\n"
            "  Genre(GenreId, Name)\n"
            "  Track(TrackId, AlbumId, GenreId, Name, ...)\n"
            "  InvoiceLine(InvoiceLineId, InvoiceId, TrackId, UnitPrice, Quantity)\n\n"
            "Fix the SQL JOIN so it correctly links Track to InvoiceLine. "
            "Do not change the output format or column names. "
            "Return ONLY the complete corrected Python file in a single code block."
        ),
        build_cmd=[sys.executable, "-m", "py_compile", "bug1_sales_genre.py"],
        test_cmd=[sys.executable, "verify_bug1.py"],
    ),
    BenchmarkTask(
        name="data-feat1-customer-ranking",
        stack="data",
        baseline="baselines/data-chinook",
        target_file="feat1_customer_ranking.py",
        prompt=(
            "Feature request: implement a SQL query using window functions to rank customers "
            "by total purchase amount within their country.\n\n"
            "Schema (relevant tables):\n"
            "  Customer(CustomerId, FirstName, LastName, Country, ...)\n"
            "  Invoice(InvoiceId, CustomerId, InvoiceDate, Total)\n\n"
            "Requirements:\n"
            "- TotalPurchases = SUM(Invoice.Total) per customer, rounded to 2 decimals\n"
            "- Rank = RANK() OVER (PARTITION BY Country ORDER BY TotalPurchases DESC)\n"
            "- Output columns (exact names): Country, CustomerId, FirstName, LastName, TotalPurchases, Rank\n"
            "- Order: Country ASC, Rank ASC\n"
            "- Save result to output_feat1.csv (already done in the template)\n\n"
            "Replace the placeholder query with the correct SQL. "
            "Return ONLY the complete corrected Python file in a single code block."
        ),
        build_cmd=[sys.executable, "-m", "py_compile", "feat1_customer_ranking.py"],
        test_cmd=[sys.executable, "verify_feat1.py"],
    ),
]

STACKS = ("springboot", "angular", "react", "data")
STACK_CSV = {
    "springboot": Path("results/metrics_springboot.csv"),
    "angular": Path("results/metrics_angular.csv"),
    "react": Path("results/metrics_react.csv"),
    "data": Path("results/metrics_data.csv"),
}
TASK_BY_NAME = {task.name: task for task in TASKS}
TASKS_BY_STACK = {stack: [task for task in TASKS if task.stack == stack] for stack in STACKS}
