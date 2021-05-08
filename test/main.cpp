#include <iostream>

class Base
{
public:
	Base()
	{
		std::cout << "Base\n";
	}
	
	~Base()
	{
		std::cout << "~Base\n";
	}
	
	void test() { std::cout << "Test\n";}
	
	int square(int a) { return a*a; }
	
};

class Derived : public Base
{
public:
	Derived() : Base() {}
	int cubed(int a) { return a*square(a); }
};


int main(int argc, char **argv)
{
	Derived d;
	
	return 0;
}
