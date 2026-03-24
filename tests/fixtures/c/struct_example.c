#include <stdlib.h>

struct Point {
    int x;
    int y;
};

typedef struct {
    int width;
    int height;
} Rectangle;

int area(struct Point *p, int scale) {
    int w = p->x * scale;
    int h = p->y * scale;
    int result = w + h;
    return result;
}
