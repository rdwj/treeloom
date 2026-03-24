import java.util.List;

public class ControlFlow {
    public String classify(int n) {
        if (n > 0) {
            return "positive";
        } else if (n < 0) {
            return "negative";
        } else {
            return "zero";
        }
    }

    public int sumTo(int n) {
        int total = 0;
        for (int i = 0; i <= n; i++) {
            total = total + i;
        }
        return total;
    }

    public void printAll(List<String> items) {
        for (String item : items) {
            System.out.println(item);
        }
    }

    public int countDown(int start) {
        int n = start;
        while (n > 0) {
            n = n - 1;
        }
        return n;
    }
}
