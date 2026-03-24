import java.util.List;

public interface Greeter {
    String greet(String name);
    int count();
}

class DefaultGreeter implements Greeter {
    private String prefix;

    public DefaultGreeter(String prefix) {
        this.prefix = prefix;
    }

    public String greet(String name) {
        String result = this.prefix + name;
        return result;
    }

    public int count() {
        return 1;
    }
}
