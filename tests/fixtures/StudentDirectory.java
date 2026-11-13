import java.util.*;

// Synthetic reference fixture, Java 17+. Immutable records and one library lock.
public final class StudentDirectory {
    public record Student(long id, String first, String last) {}
    private long nextId = 1;
    private final Map<Long, Student> students = new HashMap<>();
    private final Map<String, Set<Long>> fullNames = new HashMap<>();
    private final NavigableMap<String, Set<Long>> firstNames = new TreeMap<>();

    private static String normalize(String value) {
        return Objects.requireNonNull(value).trim().replaceAll("\\s+", " ").toLowerCase(Locale.ROOT);
    }
    private static String fullName(Student student) {
        return normalize(student.first() + " " + student.last());
    }
    private void index(Student student) {
        fullNames.computeIfAbsent(fullName(student), key -> new HashSet<>()).add(student.id());
        firstNames.computeIfAbsent(normalize(student.first()), key -> new HashSet<>()).add(student.id());
    }
    private static void removeIndex(Map<String, Set<Long>> index, String key, long id) {
        Set<Long> ids = index.get(key);
        ids.remove(id);
        if (ids.isEmpty()) index.remove(key);
    }
    public synchronized Student add(String first, String last) {
        first = normalize(first);
        last = normalize(last);
        Student student = new Student(nextId++, first, last);
        students.put(student.id(), student);
        index(student);
        return student;
    }
    public synchronized Student update(long id, String first, String last) {
        // Validate before changing either index; ordinary invalid input is atomic.
        Student replacement = new Student(id, normalize(first), normalize(last));
        Student previous = students.get(id);
        if (previous == null) throw new IllegalArgumentException("Unknown student ID");
        removeIndex(fullNames, fullName(previous), id);
        removeIndex(firstNames, normalize(previous.first()), id);
        students.put(id, replacement);
        index(replacement);
        return replacement;
    }
    public synchronized List<Student> exact(String name) {
        List<Student> result = new ArrayList<>();
        for (long id : fullNames.getOrDefault(normalize(name), Set.of())) result.add(students.get(id));
        return List.copyOf(result);
    }
    public synchronized List<Student> prefix(String prefix) {
        String normalized = normalize(prefix);
        List<Student> result = new ArrayList<>();
        for (var entry : firstNames.tailMap(normalized, true).entrySet()) {
            if (!entry.getKey().startsWith(normalized)) break;
            for (long id : entry.getValue()) result.add(students.get(id));
        }
        return List.copyOf(result);
    }
}
