interface User {
  name: string;
  age: number;
  email?: string;
}

interface Repository<T> {
  findById(id: number): T;
  save(entity: T): void;
}

enum Direction {
  North,
  South,
  East,
  West,
}

enum Status {
  Active = "active",
  Inactive = "inactive",
}
