using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Navigation;
using System.Windows.Shapes;
using System.IO;

namespace TM3_Tools
{
    class Decoder
    {
        //function for decoding ATP files found within the BINs
        //basically just re-implements the decompression routine found in the game
        //I broke it down into 11 parts and have implemented them here
        //TODO: MAKE THE GOOGLE DOC DESCRIBING THE PARTS PRESENTABLE AND PUBLIC
        
        public static void DecodeATP(int startAddress, byte[] byteArray, String outputPath)
        {
            //Note to self: when implementing this, use integers that refer to indexes on the array as "pointers"
            //Follow the instructions in the assembly as close as possible
            //Use labels and gotos for the parts

            uint sourcePointer = (uint) startAddress + 8; //a0 in the asm, skips 8 to avoid the ATP file header


            //set up a few variables to take place of some regiseters.
            //I have no idea what these registers were being used for but they were very clearly being used
            
            uint v0 = 0x0;
            uint v1 = 0x0;
            
            uint a2 = 0x0;

            //kinda stupid way for getting around the fact that source pointer will eventually be out of bounds for byteArray
            byte[] copy = new byte[byteArray.Length * 10];
            for(int i =0; i<byteArray.Length; i++)
            {
                copy[i] = byteArray[i];
            }
            byteArray = copy;

            List<byte> destList = new List<byte>();

            //Initialization phase from the document
            byte previousByte = byteArray[sourcePointer];
            sourcePointer++;
            uint destinationPointer = 0;
            uint counter = 8;
            byte buffer;

        //The parts here will follow the parts I identified in the document
            Part1:
            //Part1
            v0 = (byte)(previousByte & 0x1);//those goes before the if because of delay slots
            if (counter == 0)
            {
                
                previousByte = byteArray[sourcePointer];
                sourcePointer++;
                counter = 8;
            }
            else
            {
                goto Part2;
            }

            Part2:
            //Part2
            counter--;//goes before the if because of delay slots
            if (v0 == 0x0)
            {
                

                buffer = byteArray[sourcePointer];
                sourcePointer++;
                previousByte = (byte)(previousByte >> 0x1);

                destinationPointer++;
                destList.Add(buffer);

                goto Part1;
            }
            else
            {
                goto Part3;
            }

            Part3:
            //Part3
            previousByte = (byte)(previousByte >> 0x1);//goes before the if because of delay slots
            if (counter == 0)
            {
                
                previousByte = byteArray[sourcePointer];
                sourcePointer++;
                counter = 8;
            }
            else
            {
                goto Part4;
            }

            Part4:
            //Part4
            v0 = (byte)(previousByte & 0x1);
            v0 = byteArray[sourcePointer]; // goes before the if because of delay slots
            if (v0 == 0x0)
            {
                goto Part7;
            }
            else
            {
                
                counter--;
                previousByte = (byte)(previousByte >> 0x1); //goes before the if because of delay slots
                if (counter != 0){
                    goto Part5;
                }
                
                previousByte = byteArray[sourcePointer];
                sourcePointer++;
                counter = 8;
                goto Part5;

            }

            Part5:
            //Part5
            v0 = (byte)(previousByte & 0x1);
            previousByte = (byte)(previousByte >> 0x1);
            counter--;
            a2 = (byte)(v0 << 0x1);// goes before the if because of delay slots
            if (counter != 0)
            {
                goto Part6;
            }
            else
            {
               
                previousByte = byteArray[sourcePointer];
                sourcePointer++;
                counter = 8;
                goto Part6;

            }

            Part6:
            //Part6
            v0 = (byte)(previousByte & 0x1);
            previousByte = (byte)(previousByte >> 0x1);
            v1 = byteArray[sourcePointer];
            sourcePointer++;
            v0 = (byte)(a2 + v0);
            counter--;

            a2 = (byte)(v0 + 0x2);//before the if statement because DELAY SLOT
            if (v1 == 0)
            {
                //DELAY SLOT BABY
                v1 = 0x100;
                
            }
            goto Part9;

        Part7:
            //Part7
            sourcePointer++;
            v1 = byteArray[sourcePointer];
            sourcePointer++;
            v0 = (byte)(v0 << 8);
            previousByte = (byte)(previousByte >> 0x1);
            v1 = (byte)(v0 | v1);
            counter--;//before the if statement because of delay slots
            if (v1 == 0x0)
            {
                goto Part11; //yay it returns!
            }
            else
            {
                
                a2 = (byte)(v1 & 0xf);
                a2 = a2 + 0x2;
                if(a2 == 0x0)
                {
                    goto Part8;
                }
                else
                {
                    v1  = (v1 >> 0x4); //delay slot bby
                    goto Part9;
                }
                
            }


            Part8:
            //Part8
            v0 = byteArray[sourcePointer];
            sourcePointer++;
            v1 = (byte)(v1 >> 4);
            a2 = (byte)(v0 + 1);
            goto Part9;
            
            Part9:
            //Part9
            v1 = (byte)(destinationPointer - v1);
            if (a2 == 0)
            {
                goto Part1;
            }
            else
            {
                
                goto Part10;
            }

            Part10:
            //Part10
            v0 = byteArray[v1];
            v1++;
            a2--;
            //destination[destinationPointer] = (byte)v0;
            destList.Add((byte)v0);
            
            destinationPointer++;//before the if statement cuz delay slot
            if (a2 != 0x0)
            {
                goto Part10;
            }
            else
            {
                
                goto Part1;
            }



        Part11:

            // there's a delay slot in part 11 but it shouldn't affect output
            File.WriteAllBytes(outputPath, destList.ToArray());
            return;

        }

        public static byte[] SubArray(int startAddress, int size, byte[] byteArray)
        {
            //there are better ways to slice an array, but getting it working matters more right now
            //TODO: more efficient way to get array slices
            byte[] temp = new byte[size];

            for (int i = 0; i < size; i++)
            {
                temp[i] = byteArray[startAddress + i];
            }

            return temp;
        }
        
    }
}
