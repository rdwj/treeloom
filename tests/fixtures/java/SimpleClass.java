import java.util.List;

public class SimpleClass {
    private int value;

    public SimpleClass(int initialValue) {
        this.value = initialValue;
    }

    public int getValue() {
        return this.value;
    }

    public int add(int a, int b) {
        int result = a + b;
        return result;
    }

    public String describe(String prefix) {
        String msg = prefix + this.value;
        return msg;
    }
}
